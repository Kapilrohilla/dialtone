import userEvent from "@testing-library/user-event";
import { act, screen, waitFor, within } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import { useVoiceTest } from "./VoiceTest";

type Handler = (...args: unknown[]) => void;
type StreamHandler = (reader: AsyncIterable<string> & { info: { id: string; attributes?: Record<string, string> } }, from: { identity: string }) => Promise<void>;

/** A stand-in for livekit-client's Room: records calls and lets a test fire room events. */
class FakeRoom {
  static last: FakeRoom | null = null;
  static connectError: Error | null = null;
  static micError: Error | null = null;
  handlers = new Map<string, Handler[]>();
  streams = new Map<string, StreamHandler>();
  remoteParticipants = new Map<string, { isAgent: boolean }>();
  state = "connected";
  connect = vi.fn(async () => {
    if (FakeRoom.connectError) throw FakeRoom.connectError;
  });
  disconnect = vi.fn(async () => {
    this.state = "disconnected";
    this.emit("disconnected");
  });
  startAudio = vi.fn(async () => {});
  localParticipant = {
    identity: "web-test-1",
    setMicrophoneEnabled: vi.fn(async () => {
      if (FakeRoom.micError) throw FakeRoom.micError;
    }),
  };
  constructor() {
    FakeRoom.last = this;
  }
  on(event: string, fn: Handler) {
    this.handlers.set(event, [...(this.handlers.get(event) ?? []), fn]);
    return this;
  }
  emit(event: string, ...args: unknown[]) {
    for (const fn of this.handlers.get(event) ?? []) fn(...args);
  }
  registerTextStreamHandler(topic: string, fn: StreamHandler) {
    this.streams.set(topic, fn);
  }
  async stream(identity: string, segment: string, chunks: string[]) {
    const reader = {
      info: { id: `stream-${segment}`, attributes: { "lk.segment_id": segment } },
      async *[Symbol.asyncIterator]() {
        yield* chunks;
      },
    };
    await this.streams.get("lk.transcription")!(reader, { identity });
  }
}

vi.mock("livekit-client", () => ({
  Room: function Room() {
    return new FakeRoom();
  },
  RoomEvent: {
    TrackSubscribed: "trackSubscribed",
    TrackUnsubscribed: "trackUnsubscribed",
    ParticipantConnected: "participantConnected",
    ParticipantDisconnected: "participantDisconnected",
    ParticipantAttributesChanged: "participantAttributesChanged",
    Reconnecting: "reconnecting",
    SignalReconnecting: "signalReconnecting",
    Reconnected: "reconnected",
    Disconnected: "disconnected",
  },
  ConnectionState: { Disconnected: "disconnected", Connected: "connected" },
  Track: { Kind: { Audio: "audio" } },
}));

function serveToken(status = 200) {
  const calls: string[] = [];
  server.use(
    http.post("*/api/agents/3/web-call", ({ request }) => {
      calls.push(request.url);
      return status === 200
        ? HttpResponse.json({ url: "ws://localhost:7880", token: "tok", room: "web-3-abcd" })
        : HttpResponse.json({ detail: "You can't edit this agent." }, { status });
    }),
  );
  return calls;
}

const room = () => FakeRoom.last!;

beforeEach(() => {
  FakeRoom.last = null;
  FakeRoom.connectError = null;
  FakeRoom.micError = null;
});

/** A page with the Voice test button, as the agent editor has. */
function AgentPage({ id = 3, name = "Maya" }: { id?: number; name?: string }) {
  const voice = useVoiceTest();
  return <button onClick={() => voice.start({ id, name })}>Voice test</button>;
}

function OtherPage() {
  return <p>Call history</p>;
}

/** The routed page inside the console layout (renderWithProviders supplies the voice test provider). */
let navigate: (page: ReactNode) => void = () => {};
function Pages({ initial }: { initial: ReactNode }) {
  const [page, setPage] = useState(initial);
  navigate = setPage;
  return page;
}

/** Renders the console with the agent page and starts a call. */
async function call() {
  const user = userEvent.setup();
  const view = renderWithProviders(<Pages initial={<AgentPage />} />);
  await user.click(screen.getByRole("button", { name: "Voice test" }));
  return { user, ...view };
}

const dock = () => screen.getByRole("region", { name: "Voice test" });

function setVisibility(state: "hidden" | "visible") {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
  document.dispatchEvent(new Event("visibilitychange"));
}

beforeEach(() => setVisibility("visible"));

describe("VoiceTest", () => {
  it("connects with the dashboard's token, turns the mic on and waits for the agent", async () => {
    const calls = serveToken();
    await call();
    expect(await within(dock()).findByText("Waiting for the agent to join…")).toBeInTheDocument();
    expect(within(dock()).getByText("Maya")).toBeInTheDocument();
    expect(within(dock()).getByRole("link", { name: "Open agent" })).toHaveAttribute("href", "/agents/3");
    expect(calls).toHaveLength(1);
    expect(room().connect).toHaveBeenCalledWith("ws://localhost:7880", "tok");
    expect(room().localParticipant.setMicrophoneEnabled).toHaveBeenCalledWith(true);
    expect(room().startAudio).toHaveBeenCalled();

    act(() => room().emit("participantConnected", { isAgent: true }));
    expect(await screen.findByText(/^Connected · 0:00/)).toBeInTheDocument();
    act(() => room().emit("participantAttributesChanged", { "lk.agent.state": "speaking" }, { isAgent: true }));
    expect(await screen.findByText(/^Speaking · /)).toBeInTheDocument();
  });

  it("shows the last two lines of the conversation from the transcription streams", async () => {
    serveToken();
    await call();
    await screen.findByText("Waiting for the agent to join…");

    await act(() => room().stream("agent-xyz", "a0", ["Hello."]));
    await act(() => room().stream("agent-xyz", "a1", ["Namaste! ", "Main Maya bol rahi hoon."]));
    await act(() => room().stream("web-test-1", "u1", ["haan"]));
    // The same segment again (still speaking): replaces, doesn't append.
    await act(() => room().stream("web-test-1", "u1", ["haan ji boliye"]));

    const log = screen.getByRole("log", { name: "Conversation" });
    expect(log).toHaveTextContent("Agent Namaste! Main Maya bol rahi hoon.");
    expect(log).toHaveTextContent("You haan ji boliye");
    expect(log).not.toHaveTextContent("Hello.");
  });

  it("mutes, hangs up and calls again", async () => {
    const calls = serveToken();
    const { user } = await call();
    await screen.findByText("Waiting for the agent to join…");
    const first = room();

    await user.click(screen.getByRole("button", { name: "Mute" }));
    expect(first.localParticipant.setMicrophoneEnabled).toHaveBeenLastCalledWith(false);
    expect(screen.getByRole("button", { name: "Unmute" })).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: "Hang up" }));
    expect(first.disconnect).toHaveBeenCalled();
    expect(screen.getByText("The call ended.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Call again" }));
    await screen.findByText("Waiting for the agent to join…");
    expect(calls).toHaveLength(2);
    expect(room()).not.toBe(first);
  });

  it("collapses to a pill with a timer and a hang-up button", async () => {
    serveToken();
    const { user } = await call();
    await screen.findByText("Waiting for the agent to join…");
    act(() => room().emit("participantConnected", { isAgent: true }));
    await screen.findByText(/^Connected · 0:00/);

    await user.click(screen.getByRole("button", { name: "Collapse" }));
    expect(screen.queryByText(/^Connected/)).not.toBeInTheDocument();
    expect(within(dock()).getByText("0:00")).toBeInTheDocument();
    await user.click(within(dock()).getByRole("button", { name: "Open voice test" }));
    expect(screen.getByText(/^Connected · 0:00/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Collapse" }));
    await user.click(within(dock()).getByRole("button", { name: "Hang up" }));
    expect(room().disconnect).toHaveBeenCalled();
    expect(screen.getByText("The call ended.")).toBeInTheDocument();
  });

  it("ends when the room disconnects", async () => {
    serveToken();
    await call();
    await screen.findByText("Waiting for the agent to join…");
    act(() => room().emit("disconnected"));
    expect(await screen.findByText("The call ended.")).toBeInTheDocument();
  });

  it("ends when the agent leaves, and drops the room", async () => {
    serveToken();
    await call();
    await screen.findByText("Waiting for the agent to join…");
    act(() => room().emit("participantConnected", { isAgent: true }));
    await screen.findByText(/^Connected · /);
    // Someone else leaving isn't the end.
    act(() => room().emit("participantDisconnected", { isAgent: false }));
    expect(screen.getByText(/^Connected · /)).toBeInTheDocument();

    act(() => room().emit("participantDisconnected", { isAgent: true }));
    expect(await screen.findByText("The call ended.")).toBeInTheDocument();
    expect(room().disconnect).toHaveBeenCalled();
    expect(screen.queryByText(/^Connected/)).not.toBeInTheDocument();
  });

  it("says it's reconnecting, and ends when the reconnect fails", async () => {
    serveToken();
    await call();
    await screen.findByText("Waiting for the agent to join…");
    act(() => room().emit("participantConnected", { isAgent: true }));
    await screen.findByText(/^Connected · /);

    act(() => room().emit("reconnecting"));
    expect(await screen.findByText("Reconnecting…")).toBeInTheDocument();
    act(() => room().emit("disconnected"));
    expect(await screen.findByText("The call ended.")).toBeInTheDocument();
    expect(screen.queryByText("Reconnecting…")).not.toBeInTheDocument();
  });

  it("ends after a reconnect if the agent is gone", async () => {
    serveToken();
    await call();
    await screen.findByText("Waiting for the agent to join…");
    act(() => room().emit("participantConnected", { isAgent: true }));
    await screen.findByText(/^Connected · /);
    act(() => room().emit("reconnecting"));
    act(() => room().emit("reconnected"));
    expect(await screen.findByText("The call ended.")).toBeInTheDocument();
  });

  it("ends a call that disconnected while the tab was hidden, once the tab is back", async () => {
    serveToken();
    await call();
    await screen.findByText("Waiting for the agent to join…");
    const r = room();
    r.remoteParticipants.set("agent", { isAgent: true });
    act(() => r.emit("participantConnected", { isAgent: true }));
    await screen.findByText(/^Connected · /);

    setVisibility("hidden");
    // The disconnect happened in the background and its event never reached the page.
    r.state = "disconnected";
    expect(screen.getByText(/^Connected · /)).toBeInTheDocument();
    act(() => setVisibility("visible"));
    expect(await screen.findByText("The call ended.")).toBeInTheDocument();
  });

  it("keeps a healthy call when the tab comes back", async () => {
    serveToken();
    await call();
    await screen.findByText("Waiting for the agent to join…");
    room().remoteParticipants.set("agent", { isAgent: true });
    act(() => room().emit("participantConnected", { isAgent: true }));
    await screen.findByText(/^Connected · /);
    setVisibility("hidden");
    act(() => setVisibility("visible"));
    expect(screen.getByText(/^Connected · /)).toBeInTheDocument();
    expect(room().disconnect).not.toHaveBeenCalled();
  });

  it("keeps the call going when you move to another console page", async () => {
    serveToken();
    await call();
    await screen.findByText("Waiting for the agent to join…");
    act(() => room().emit("participantConnected", { isAgent: true }));
    await screen.findByText(/^Connected · /);

    act(() => navigate(<OtherPage />));
    expect(screen.getByText("Call history")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Voice test" })).not.toBeInTheDocument();
    expect(within(dock()).getByText(/^Connected · /)).toBeInTheDocument();
    expect(room().disconnect).not.toHaveBeenCalled();
  });

  it("opening the same agent's voice test again keeps the call; another agent's replaces it", async () => {
    const calls = serveToken();
    server.use(http.post("*/api/agents/4/web-call", () => HttpResponse.json({ url: "ws://localhost:7880", token: "tok4", room: "web-4" })));
    const { user } = await call();
    await screen.findByText("Waiting for the agent to join…");
    const first = room();
    await user.click(screen.getByRole("button", { name: "Collapse" }));
    await user.click(screen.getByRole("button", { name: "Voice test" }));
    expect(screen.getByText("Waiting for the agent to join…")).toBeInTheDocument();
    expect(calls).toHaveLength(1);

    act(() => navigate(<AgentPage id={4} name="Ravi" />));
    await user.click(screen.getByRole("button", { name: "Voice test" }));
    await waitFor(() => expect(room()).not.toBe(first));
    expect(first.disconnect).toHaveBeenCalled();
    expect(await within(dock()).findByText("Ravi")).toBeInTheDocument();
    await waitFor(() => expect(room().connect).toHaveBeenCalledWith("ws://localhost:7880", "tok4"));
  });

  it("hangs up when the browser tab closes", async () => {
    serveToken();
    await call();
    await screen.findByText("Waiting for the agent to join…");
    window.dispatchEvent(new Event("pagehide"));
    expect(room().disconnect).toHaveBeenCalled();
  });

  it("explains when LiveKit can't be reached", async () => {
    serveToken();
    FakeRoom.connectError = new Error("could not establish signal connection");
    await call();
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't reach LiveKit at ws://localhost:7880");
    expect(screen.getByText("The call didn't start.")).toBeInTheDocument();
  });

  it("explains a blocked microphone and hangs up", async () => {
    serveToken();
    FakeRoom.micError = Object.assign(new Error("denied"), { name: "NotAllowedError" });
    await call();
    expect(await screen.findByRole("alert")).toHaveTextContent("The browser blocked the microphone");
    await waitFor(() => expect(room().disconnect).toHaveBeenCalled());
    expect(screen.getByText("The call didn't start.")).toBeInTheDocument();
  });

  it("shows the dashboard's error when there's no token, and closes", async () => {
    serveToken(403);
    const { user } = await call();
    expect(await screen.findByRole("alert")).toHaveTextContent("You can't edit this agent.");
    expect(FakeRoom.last).toBeNull();
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("region", { name: "Voice test" })).not.toBeInTheDocument();
  });

  it("hangs up when the console goes away", async () => {
    serveToken();
    const { unmount } = await call();
    await screen.findByText("Waiting for the agent to join…");
    unmount();
    expect(room().disconnect).toHaveBeenCalled();
  });
});
