/**
 * The egress-policy form's pure half (§264).
 *
 * `apps/api/tests/test_egress.py` is what a set of policies *means*; this is
 * what a form may say about one before it is sent, and what the panel puts
 * beside the list. The two overlap on purpose and the server is the authority
 * — `problem` existing does not make `egress.parse` optional.
 *
 * `data-connection` pages are `p.N`.
 */
import { describe as group, expect, test } from "vitest";

import {
  blankPolicy,
  describe,
  destinationsFor,
  draftFor,
  problem,
  summary,
  toPayload,
  urlDestination,
  type Policy,
} from "./egress-policy";

function policy(host: string, port: number | null = null, id = host): Policy {
  return { id, host, port, description: "" };
}

function draft(host: string, port = "", description = "") {
  return { host, port, description };
}

group("what a form may refuse", () => {
  test("a blank draft is refused before it can be sent", () => {
    expect(problem(blankPolicy())).toBe("Name the host this source may reach.");
  });

  test("a plain host is accepted", () => {
    expect(problem(draft("api.example.com"))).toBeNull();
  });

  test("an address is a destination too", () => {
    // p.103 pushes towards names, but "this one host" is a legitimate thing to
    // say and refusing it would refuse the case p.103 describes a workaround
    // for.
    expect(problem(draft("10.0.0.1"))).toBeNull();
  });

  test("a range is refused and the message offers the alternative", () => {
    const said = problem(draft("10.0.0.0/8"));
    expect(said).toContain("not a range");
    expect(said).toContain("name each host");
  });

  test("something that is not a hostname is refused and quoted back", () => {
    // Quoted back because the two most likely mistakes - pasting a URL, and a
    // trailing space - are both invisible in a message that does not repeat
    // the input.
    expect(problem(draft("https://api.example.com"))).toContain("https://api.example.com");
    for (const host of ["   ", "api example.com", "-lead", "trail-"]) {
      expect(problem(draft(host))).not.toBeNull();
    }
  });

  test("a host longer than a hostname may be is refused", () => {
    expect(problem(draft(`${"a".repeat(254)}`))).toContain("not a hostname");
  });

  test("case and surrounding space do not make a host wrong", () => {
    // The server lowercases rather than refusing, and a form that refused what
    // the server accepts would be a guard with a one-keystroke bypass in the
    // other direction: somebody retyping until the red text goes away.
    expect(problem(draft("  API.Example.COM  "))).toBeNull();
  });

  test("a port that is not a number is refused", () => {
    expect(problem(draft("api.example.com", "https"))).toContain("not a port");
    expect(problem(draft("api.example.com", "-1"))).toContain("not a port");
  });

  test("a port outside the range is refused at both ends", () => {
    // Both ends, because a check written against one bound passes every test
    // that only tries the other.
    expect(problem(draft("api.example.com", "0"))).toContain("not a port");
    expect(problem(draft("api.example.com", "65536"))).toContain("not a port");
    expect(problem(draft("api.example.com", "1"))).toBeNull();
    expect(problem(draft("api.example.com", "65535"))).toBeNull();
  });

  test("an empty port is any port, not port zero", () => {
    expect(problem(draft("api.example.com", ""))).toBeNull();
    expect(toPayload(draft("api.example.com", "")).port).toBeNull();
  });
});

group("the duplicate a form can see coming", () => {
  test("the same host and port as an existing policy is refused by name", () => {
    const said = problem(draft("api.example.com", "443"), [policy("api.example.com", 443)]);
    expect(said).toBe("This source already allows api.example.com:443.");
  });

  test("the same host on another port is a different destination", () => {
    // The presence half. Without it the check above passes against a form that
    // refuses every second policy for a host.
    expect(problem(draft("api.example.com", "8443"), [policy("api.example.com", 443)])).toBeNull();
  });

  test("a host with no port clashes with the stored one that has none", () => {
    // `NULLS NOT DISTINCT` in db 0068, and the case a JavaScript `===` gets
    // right only because both sides are normalised to null first.
    expect(problem(draft("api.example.com"), [policy("api.example.com", null)])).not.toBeNull();
  });

  test("a host with no port does not clash with one that names a port", () => {
    expect(problem(draft("api.example.com"), [policy("api.example.com", 443)])).toBeNull();
  });

  test("the clash is found through case, because the stored host is lowercase", () => {
    expect(problem(draft("API.Example.com"), [policy("api.example.com")])).not.toBeNull();
  });

  test("another host on the same port is not a clash", () => {
    // **§264's harness found this one missing**, and the shape is §190's: every
    // other case here varies the *port* while holding the host, so a check that
    // had dropped the host comparison entirely still passed all five. A test
    // about keying needs fixtures that collide on everything except the key,
    // and until this one the host was never the thing that differed.
    expect(
      problem(draft("other.example.com", "443"), [policy("api.example.com", 443)]),
    ).toBeNull();
  });
});

group("what is sent", () => {
  test("a draft is normalised the way the server would store it", () => {
    expect(toPayload(draft("  API.Example.COM  ", " 443 ", "  the vendor API  "))).toEqual({
      host: "api.example.com",
      port: 443,
      description: "the vendor API",
    });
  });
});

group("what the list says about itself", () => {
  test("an empty list says it means unrestricted", () => {
    // Decision 0013 §2. An empty table with no sentence over it reads as the
    // opposite of what it means, and this is the one control whose off state
    // and on state would otherwise look identical.
    const said = summary([]);
    expect(said).toContain("any destination");
    expect(said).toContain("Add one");
  });

  test("a non-empty list says the source is restricted and to how many", () => {
    expect(summary([policy("a.example.com")])).toContain("the one destination");
    expect(summary([policy("a.example.com"), policy("b.example.com")])).toContain(
      "the 2 destinations",
    );
    expect(summary([policy("a.example.com")])).toContain("nothing else");
  });

  test("a destination reads the way the server's refusal spells it", () => {
    // So somebody reading "not allowed to reach api.example.com:443" can find
    // that string in the table without translating it.
    expect(describe({ host: "api.example.com", port: 443 })).toBe("api.example.com:443");
    expect(describe({ host: "api.example.com", port: null })).toBe("api.example.com");
  });
});

group("the destination a URL means", () => {
  test("an explicit port is the destination", () => {
    expect(urlDestination("https://api.example.com:8443/v1")).toEqual({
      host: "api.example.com",
      port: 8443,
    });
  });

  test("a scheme supplies the port the URL left out", () => {
    // Both schemes, and they differ - a single case would pass against a
    // constant.
    expect(urlDestination("https://api.example.com/v1")?.port).toBe(443);
    expect(urlDestination("http://api.example.com/v1")?.port).toBe(80);
  });

  test("a scheme with no implied port supplies nothing rather than guessing", () => {
    expect(urlDestination("ftp://files.example.com")).toEqual({
      host: "files.example.com",
      port: null,
    });
  });

  test("the host comes back lowercase, as the policies it is compared against are", () => {
    // Provided by `URL` rather than by a call this module makes — §264's
    // harness proved the `.toLowerCase()` that used to be there could not be
    // made to fail, so it was deleted. The property is still the one every
    // caller depends on, and this is what would go red if the parser were
    // swapped for a regex.
    expect(urlDestination("https://API.Example.COM")?.host).toBe("api.example.com");
  });

  test("userinfo is not the host", () => {
    // `https://api.example.com@evil.example.net` dials **evil**, and a regex
    // written around `//` and the first `/` reports the wrong one. This is why
    // the implementation uses `URL` rather than a pattern.
    expect(urlDestination("https://api.example.com@evil.example.net/v1")?.host).toBe(
      "evil.example.net",
    );
  });

  test("something that is not a URL is nothing, not a guess", () => {
    for (const text of ["", "   ", "api.example.com", "not a url"]) {
      expect(urlDestination(text)).toBeNull();
    }
  });
});

group("what a source is configured to reach", () => {
  test("a database source's host and port", () => {
    expect(destinationsFor("postgres", { host: "Warehouse.Example.com", port: 5432 })).toEqual({
      known: [{ label: "Database host", host: "warehouse.example.com", port: 5432 }],
      caveat: null,
    });
  });

  test("mysql is read the same way and its own port is not postgres's", () => {
    // The two connectors have different defaults, so a fixture using 5432 for
    // both would pass against an implementation that hard-coded one.
    expect(destinationsFor("mysql", { host: "db.example.com", port: 3306 }).known).toEqual([
      { label: "Database host", host: "db.example.com", port: 3306 },
    ]);
  });

  test("a database source with no host says so rather than reporting none", () => {
    const found = destinationsFor("postgres", { port: 5432 });
    expect(found.known).toEqual([]);
    expect(found.caveat).not.toBeNull();
  });

  test("a REST source's base URL", () => {
    expect(destinationsFor("rest", { base_url: "https://api.example.com/v2" }).known).toEqual([
      { label: "Base URL", host: "api.example.com", port: 443 },
    ]);
  });

  test("a REST source using OAuth reaches its token endpoint too", () => {
    // p.12's two-destination source, and the one §263 found unguarded. On a
    // *different host* from the base URL, because a fixture sharing one host
    // would pass against an implementation that reported the base URL twice.
    const found = destinationsFor("rest", {
      base_url: "https://api.example.com/v2",
      auth_type: "oauth2_client_credentials",
      token_url: "https://login.vendor.example.net/oauth/token",
    });
    expect(found.known).toEqual([
      { label: "Base URL", host: "api.example.com", port: 443 },
      { label: "Token endpoint", host: "login.vendor.example.net", port: 443 },
    ]);
  });

  test("a token URL left over from another auth type is not a destination", () => {
    // `RestConfig` keeps `token_url` whatever `auth_type` says, so a source
    // switched to `bearer` can still carry one - and it is not dialled. The
    // absence half of the test above: without it, that one passes against an
    // implementation that always reports `token_url`.
    const found = destinationsFor("rest", {
      base_url: "https://api.example.com/v2",
      auth_type: "bearer",
      token_url: "https://login.vendor.example.net/oauth/token",
    });
    expect(found.known.map((d) => d.label)).toEqual(["Base URL"]);
  });

  test("a REST source with nothing readable says so", () => {
    const found = destinationsFor("rest", { base_url: "" });
    expect(found.known).toEqual([]);
    expect(found.caveat).not.toBeNull();
  });

  test("an S3 source with a custom endpoint has one destination", () => {
    expect(destinationsFor("s3", { bucket: "landing", endpoint_url: "https://minio.internal:9000" })).toEqual(
      { known: [{ label: "Custom endpoint", host: "minio.internal", port: 9000 }], caveat: null },
    );
  });

  test("an AWS bucket reports no destinations and says why", () => {
    // The gap `S3Connector._client` documents and §263's own test holds on the
    // server. Somebody who adds a policy to an AWS bucket has to be told it
    // changed nothing - an empty list on its own would read as "nothing to
    // restrict", which is the opposite.
    const found = destinationsFor("s3", { bucket: "landing", region: "eu-west-2" });
    expect(found.known).toEqual([]);
    expect(found.caveat).toContain("cannot restrict this source");
    expect(found.caveat).toContain("custom endpoint");
  });

  test("a source type this does not know is a caveat, never a bare empty list", () => {
    // "No destinations" and "I cannot read this source's destinations" are
    // different answers, and only one of them means the list of policies below
    // is the whole picture. This is also what makes adding a connector without
    // coming here visible.
    const found = destinationsFor("kafka", { brokers: "a,b" });
    expect(found.known).toEqual([]);
    expect(found.caveat).toContain("kafka");
  });

  test("a missing config is read as an empty one rather than throwing", () => {
    expect(destinationsFor("postgres", null).known).toEqual([]);
    expect(destinationsFor("rest", undefined).known).toEqual([]);
  });
});

group("suggesting a policy", () => {
  test("a destination becomes a draft that would be accepted", () => {
    const made = draftFor({ label: "Base URL", host: "api.example.com", port: 443 });
    expect(made).toEqual({
      host: "api.example.com",
      port: "443",
      description: "This source's base url",
    });
    expect(problem(made)).toBeNull();
  });

  test("a destination with no port becomes a draft with an empty port", () => {
    // Not "null" and not "0": the field is text, and either of those would be
    // a port the form then refuses.
    expect(draftFor({ label: "Database host", host: "db.example.com", port: null }).port).toBe("");
  });
});
