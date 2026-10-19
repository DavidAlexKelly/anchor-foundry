import { describe, expect, it, vi } from "vitest";
import type { KeyboardEvent } from "react";
import { pressable } from "./pressable";

function key(name: string) {
  return { key: name, preventDefault: vi.fn(), stopPropagation: vi.fn() } as unknown as KeyboardEvent & {
    preventDefault: ReturnType<typeof vi.fn>;
  };
}

describe("a shape that acts as a button", () => {
  it("is one, and takes focus", () => {
    const props = pressable(() => {});
    expect(props.role).toBe("button");
    expect(props.tabIndex).toBe(0);
  });

  it("is pressed by a click, Enter and Space, as a button is", () => {
    const pressed = vi.fn();
    const props = pressable(pressed);
    props.onClick();
    props.onKeyDown(key("Enter"));
    props.onKeyDown(key(" "));
    expect(pressed).toHaveBeenCalledTimes(3);
  });

  it("and by nothing else - a Tab moves past it", () => {
    const pressed = vi.fn();
    const tab = key("Tab");
    pressable(pressed).onKeyDown(tab);
    expect(pressed).not.toHaveBeenCalled();
    expect(tab.preventDefault).not.toHaveBeenCalled();
  });

  it("keeps Space from scrolling the page", () => {
    const space = key(" ");
    pressable(() => {}).onKeyDown(space);
    expect(space.preventDefault).toHaveBeenCalled();
  });
});
