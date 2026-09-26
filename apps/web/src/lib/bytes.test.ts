import { describe, expect, it } from "vitest";

import { bytesText } from "./bytes";

describe("bytesText", () => {
  it("says bytes under a kilobyte as bytes", () => {
    expect(bytesText(0)).toBe("0 B");
    expect(bytesText(1023)).toBe("1023 B");
  });

  it("keeps a decimal below ten and drops it above", () => {
    expect(bytesText(1024)).toBe("1.0 KB");
    expect(bytesText(1536)).toBe("1.5 KB");
    expect(bytesText(10 * 1024)).toBe("10 KB");
    expect(bytesText(24 * 1024 * 1024)).toBe("24 MB");
    expect(bytesText(3 * 1024 ** 3)).toBe("3.0 GB");
  });

  it("stops at terabytes", () => {
    expect(bytesText(2048 * 1024 ** 4)).toBe("2048 TB");
  });
});
