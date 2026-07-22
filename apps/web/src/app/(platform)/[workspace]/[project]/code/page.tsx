"use client";

export default function Page() {
  return (
    <main>
      <div className="page-head">
        <div>
          <p className="eyebrow">project · code</p>
          <h1>Code</h1>
        </div>
      </div>
      <div className="empty">
        <h2>No repositories yet</h2>
        <p>Code repositories are power mode: transforms, custom widgets, and functions in real Git, deployed into the same project non-developers work in.</p>
        <button className="btn" disabled title="Coming in the next milestone">
          New repository
        </button>
      </div>
    </main>
  );
}
