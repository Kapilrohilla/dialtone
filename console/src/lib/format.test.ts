import { describe, expect, it } from "vitest";
import { formatDuration, formatElapsed, formatPhone, formatWhen, timeAgo } from "@/lib/format";

const now = new Date("2026-11-05T10:00:00Z");

describe("format", () => {
  it("formats Indian numbers", () => {
    expect(formatPhone("+918047182290")).toBe("+91 80 4718 2290");
    expect(formatPhone("+14155550123")).toBe("+14155550123");
  });
  it("formats durations", () => {
    expect(formatDuration(125)).toBe("2:05");
    expect(formatDuration(3725)).toBe("1:02:05");
    expect(formatDuration(null)).toBe("—");
  });
  it("formats call times in the user's time zone", () => {
    expect(formatWhen("2026-11-05T09:02:00Z", "Asia/Kolkata", now)).toBe("Today 14:32");
    expect(formatWhen("2026-11-04T03:40:00Z", "Asia/Kolkata", now)).toBe("Yesterday 09:10");
    expect(formatWhen("2026-10-20T09:02:00Z", "Asia/Kolkata", now)).toBe("20 Oct 14:32");
    expect(formatWhen("2026-11-04T20:00:00Z", "Asia/Kolkata", now)).toBe("Today 01:30");
  });
  it("says how long ago", () => {
    expect(timeAgo("2026-11-05T09:59:40Z", now)).toBe("just now");
    expect(timeAgo("2026-11-05T09:55:00Z", now)).toBe("5 minutes ago");
    expect(timeAgo("2026-11-05T09:59:00Z", now)).toBe("1 minute ago");
    expect(timeAgo("2026-11-05T08:00:00Z", now)).toBe("2 hours ago");
    expect(timeAgo("2026-11-02T10:00:00Z", now)).toBe("3 days ago");
    expect(timeAgo("2026-10-05T10:00:00Z", now)).toBe("5 Oct");
  });
  it("formats elapsed time", () => {
    expect(formatElapsed("2026-11-05T09:57:46Z", now)).toBe("02:14");
    expect(formatElapsed("2026-11-05T08:57:55Z", now)).toBe("1:02:05");
  });
});
