"use client";

export default function Page() {
  return (
    <main>
      <div className="page-head">
        <div>
          <p className="eyebrow">project · objects</p>
          <h1>Objects</h1>
        </div>
      </div>
      <div className="empty">
        <h2>The ontology starts here</h2>
        <p>Object types give your data business meaning: a Customer, an Order, a Shipment — typed properties, typed relationships, shared across the workspace.</p>
        <button className="btn" disabled title="Coming in the next milestone">
          Define object type
        </button>
      </div>
    </main>
  );
}
