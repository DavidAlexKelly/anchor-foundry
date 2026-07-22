"use client";

export default function Page() {
  return (
    <main>
      <div className="page-head">
        <div>
          <p className="eyebrow">project · canvas</p>
          <h1>Canvas</h1>
        </div>
      </div>
      <div className="empty">
        <h2>No apps yet</h2>
        <p>Canvas apps are built from widgets bound to your objects — tables, charts, forms with write-back. No code needed; drop into code when you want it.</p>
        <button className="btn" disabled title="Coming in the next milestone">
          New canvas app
        </button>
      </div>
    </main>
  );
}
