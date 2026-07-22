/** The Anchor mark: a shackle-and-line glyph drawn from the chain motif. */
export function AnchorGlyph({ size = 18 }: { size?: number }) {
  return (
    <svg
      className="wordmark-glyph"
      width={size}
      height={size}
      viewBox="0 0 18 18"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="9" cy="4" r="2.4" stroke="currentColor" strokeWidth="1.6" />
      <path d="M9 6.5V15" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path
        d="M3.5 11.5C3.5 14 6 15.5 9 15.5C12 15.5 14.5 14 14.5 11.5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}
