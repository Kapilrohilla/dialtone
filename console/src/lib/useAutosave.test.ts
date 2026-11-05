import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { useAutosave } from "@/lib/useAutosave";

type Props = { value: string; enabled?: boolean };

function deferred() {
  let resolve!: () => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<void>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function setup(save: (v: string) => Promise<unknown>, initial = "a") {
  return renderHook(({ value, enabled }: Props) => useAutosave(value, save, 800, enabled), { initialProps: { value: initial } as Props });
}

describe("useAutosave", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not save the first value", async () => {
    const save = vi.fn(() => Promise.resolve());
    setup(save);
    await act(() => vi.advanceTimersByTimeAsync(2000));
    expect(save).not.toHaveBeenCalled();
  });

  it("debounces and saves the latest value once", async () => {
    const save = vi.fn(() => Promise.resolve());
    const { result, rerender } = setup(save);
    rerender({ value: "b" });
    await act(() => vi.advanceTimersByTimeAsync(250));
    rerender({ value: "c" });
    await act(() => vi.advanceTimersByTimeAsync(250));
    rerender({ value: "d" });
    await act(() => vi.advanceTimersByTimeAsync(799));
    expect(save).not.toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith("d");
    expect(result.current.status).toBe("saved");
  });

  it("queues a change made during a save", async () => {
    const first = deferred();
    const save = vi.fn((v: string) => (v === "b" ? first.promise : Promise.resolve()));
    const { result, rerender } = setup(save);
    rerender({ value: "b" });
    await act(() => vi.advanceTimersByTimeAsync(800));
    expect(result.current.status).toBe("saving");
    rerender({ value: "c" });
    await act(() => vi.advanceTimersByTimeAsync(2000));
    expect(save).toHaveBeenCalledTimes(1);
    await act(async () => first.resolve());
    expect(save).toHaveBeenCalledTimes(2);
    expect(save).toHaveBeenLastCalledWith("c");
    expect(result.current.status).toBe("saved");
  });

  it("flush saves immediately", async () => {
    const save = vi.fn(() => Promise.resolve());
    const { result, rerender } = setup(save);
    rerender({ value: "b" });
    await act(() => result.current.flush());
    expect(save).toHaveBeenCalledWith("b");
    await act(() => vi.advanceTimersByTimeAsync(2000));
    expect(save).toHaveBeenCalledTimes(1);
  });

  it("flush with nothing changed resolves without saving", async () => {
    const save = vi.fn(() => Promise.resolve());
    const { result } = setup(save);
    await act(() => result.current.flush());
    expect(save).not.toHaveBeenCalled();
  });

  it("reports an error, rejects flush, and saves again on the next change", async () => {
    const err = new ApiError(400, "Too long.");
    const save = vi.fn((v: string) => (v === "b" ? Promise.reject(err) : Promise.resolve()));
    const { result, rerender } = setup(save);
    rerender({ value: "b" });
    await act(async () => {
      await expect(result.current.flush()).rejects.toBe(err);
    });
    expect(result.current.status).toBe("error");
    expect(result.current.error).toBe(err);
    rerender({ value: "c" });
    await act(() => vi.advanceTimersByTimeAsync(800));
    expect(save).toHaveBeenLastCalledWith("c");
    expect(result.current.status).toBe("saved");
    expect(result.current.error).toBeUndefined();
  });

  it("stops saving while disabled", async () => {
    const save = vi.fn(() => Promise.resolve());
    const { rerender } = setup(save);
    rerender({ value: "b", enabled: false });
    await act(() => vi.advanceTimersByTimeAsync(2000));
    expect(save).not.toHaveBeenCalled();
  });
});
