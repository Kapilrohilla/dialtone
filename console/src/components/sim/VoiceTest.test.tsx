import userEvent from "@testing-library/user-event";
import { act, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import { VoiceTest } from "./VoiceTest";

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
  connect = vi.fn(async () => {
    if (FakeRoom.connectError) throw FakeRoom.connectError;
  });
  disconnect = vi.fn(async () => {
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
    ParticipantAttributesChanged: "participantAttributesChanged",
    Disconnected: "disconnected",
  },
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

describe("VoiceTest", () => {
  it("connects with the dashboard's token, turns the mic on and waits for the agent", async () => {
    const calls = serveToken();
    renderWithProviders(<VoiceTest agentId={3} onClose={() => {}} />);
    expect(screen.getByRole("dialog", { name: "Voice test" })).toBeInTheDocument();
    expect(await screen.findByText("Waiting for the agent to join…")).toBeInTheDocument();
    expect(calls).toHaveLength(1);
    expect(room().connect).toHaveBeenCalledWith("ws://localhost:7880", "tok");
    expect(room().localParticipant.setMicrophoneEnabled).toHaveBeenCalledWith(true);
    expect(room().startAudio).toHaveBeenCalled();

    act(() => room().emit("participantConnected", { isAgent: true }));
    expect(await screen.findByText(/^Connected · 0:00/)).toBeInTheDocument();
    act(() => room().emit("participantAttributesChanged", { "lk.agent.state": "speaking" }, { isAgent: true }));
    expect(await screen.findByText(/^Speaking · /)).toBeInTheDocument();
  });

  it("shows both sides of the conversation from the transcription streams", async () => {
    serveToken();
    renderWithProviders(<VoiceTest agentId={3} onClose={() => {}} />);
    await screen.findByText("Waiting for the agent to join…");

    await act(() => room().stream("agent-xyz", "a1", ["Namaste! ", "Main Priya bol rahi hoon."]));
    await act(() => room().stream("web-test-1", "u1", ["haan"]));
    // The same segment again (still speaking): replaces, doesn't append.
    await act(() => room().stream("web-test-1", "u1", ["haan ji boliye"]));

    const log = screen.getByRole("log", { name: "Conversation" });
    expect(within(log).getByText("Namaste! Main Priya bol rahi hoon.")).toBeInTheDocument();
    expect(within(log).getByText("haan ji boliye")).toBeInTheDocument();
    expect(within(log).queryByText("haan")).not.toBeInTheDocument();
    expect(within(log).getAllByText(/^(You|Agent)$/).map((n) => n.textContent)).toEqual(["Agent", "You"]);
  });

  it("mutes, hangs up and calls again", async () => {
    const calls = serveToken();
    const user = userEvent.setup();
    renderWithProviders(<VoiceTest agentId={3} onClose={() => {}} />);
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

  it("ends when the agent hangs up", async () => {
    serveToken();
    renderWithProviders(<VoiceTest agentId={3} onClose={() => {}} />);
    await screen.findByText("Waiting for the agent to join…");
    act(() => room().emit("disconnected"));
    expect(await screen.findByText("The call ended.")).toBeInTheDocument();
  });

  it("explains when LiveKit can't be reached", async () => {
    serveToken();
    FakeRoom.connectError = new Error("could not establish signal connection");
    renderWithProviders(<VoiceTest agentId={3} onClose={() => {}} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't reach LiveKit at ws://localhost:7880");
    expect(screen.getByText("The call didn't start.")).toBeInTheDocument();
  });

  it("explains a blocked microphone and hangs up", async () => {
    serveToken();
    FakeRoom.micError = Object.assign(new Error("denied"), { name: "NotAllowedError" });
    renderWithProviders(<VoiceTest agentId={3} onClose={() => {}} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The browser blocked the microphone");
    await waitFor(() => expect(room().disconnect).toHaveBeenCalled());
    expect(screen.getByText("The call didn't start.")).toBeInTheDocument();
  });

  it("shows the dashboard's error when there's no token", async () => {
    serveToken(403);
    renderWithProviders(<VoiceTest agentId={3} onClose={() => {}} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("You can't edit this agent.");
    expect(FakeRoom.last).toBeNull();
  });

  it("hangs up when closed", async () => {
    serveToken();
    const { unmount } = renderWithProviders(<VoiceTest agentId={3} onClose={() => {}} />);
    await screen.findByText("Waiting for the agent to join…");
    unmount();
    expect(room().disconnect).toHaveBeenCalled();
  });
});
