# Render Artifact

> **Reporter v2 (spec 0061).** The render is the `render-html` or `render-markdown` typed
> [output part](REPORT.md) that platform UI surfaces embed — an episode page, a report viewer, a
> post in The Column. The safe profile below is enforced **at emit time**: `output.emit` returns a
> typed error to the running reporter the moment an unsafe render is emitted.

A reporter that wants an embeddable surface declares a render part in its version attributes and
emits it during the run:

```
output.emit("recap", render-html("<html>…</html>"))
```

Render parts are optional — a reporter with no render part is still valid; it just has nothing to
embed.

## Why this needs a contract

Reporters are author-supplied programs. Their output is **untrusted**: an author could,
deliberately or accidentally, emit a render that runs JavaScript, phones home with a tracking
pixel, or redirects the page. The platform embeds that content in a first-party surface, so the
render part needs a contract that is safe to embed even when the author is adversarial.

The contract is **defense in depth**: a safe authoring profile enforced when the part is emitted,
*plus* a sandboxed rendering boundary the platform always applies. Neither layer is trusted alone.

## Safe Render Profile (producer side)

The render part must be **self-contained**: there is no surrounding zip, so every asset it uses is
inline — `data:` URIs for images and fonts, inline `<style>`, inline SVG. It must not load
resources from the network or reference external files. `output.emit` statically checks every
render emission and returns a typed error — listing each violation — if the content breaks the
profile.

### Markdown (`render-markdown`) — recommended default

Markdown is the simplest safe render format. The platform renders it with a CommonMark renderer
that has **raw HTML disabled**: any embedded HTML is escaped to visible text rather than parsed.
That makes Markdown safe by construction, so any UTF-8 Markdown payload is accepted. Use Markdown
unless you need layout or inline charts Markdown cannot express.

### HTML (`render-html`) — for rich reports

An HTML render part may use tables, inline styles, `data:` images and fonts, and inline SVG for
charts, but it must obey these rules. `output.emit` rejects any payload that breaks them:

| Rule | Rejected examples |
| --- | --- |
| **No inline/event-handler scripting.** | Inline `<script>...</script>`, `on*` handler attributes (`onclick`, `onload`, ...), `href="javascript:..."` |
| **No embedding or navigation sinks.** | `<iframe>`, `<frame>`, `<object>`, `<embed>`, `<applet>`, `<form>`, `<base>`, `<meta http-equiv>` |
| **No external or file loads.** Resource URLs (`src`, `srcset`, `poster`, `background`, `data`, `xlink:href`, stylesheet `href`) must be inline `data:` payloads or `#` fragments. | `<img src="https://tracker.example/p.gif">`, `<img src="./chart.png">`, `<link rel="stylesheet" href="https://example.com/report.css">` |
| **No unsafe CSS.** `<style>` blocks and `style=` attributes must not contain `javascript:`, `expression(`, `@import`, or `url()` pointing anywhere but a `data:` payload or `#` fragment. | `style="background:url(https://x/y.png)"`, `@import url(...)` |

What this leaves you: text and structural elements, headings, lists, tables, inline `<style>` and
`style=` attributes, `data:` images and fonts, and `<svg>` charts. Hyperlinks (`<a href>`) may
point at `http(s)`/`mailto` targets — they navigate only when a user clicks them; only
script-bearing schemes are rejected.

> **Self-contained means self-contained.** Because external and relative resource URLs are both
> rejected, an HTML render part carries its own CSS, images, and fonts as inline or `data:`
> payloads. This keeps renders reproducible, embeddable offline, and free of phone-home vectors.
> `<img src="data:image/svg+xml,...">` is allowed even for SVG: browsers do not execute scripts in
> SVG loaded through `<img>`. Inline `<svg>...</svg>` in the document body *is* scanned for
> scripting, because inline SVG can carry it.

## Rendering Contract (platform side)

The emit-time check is fast author-facing feedback, not the security boundary. Any platform
surface that renders a report part must embed it inside a **sandboxed iframe** served under a
strict **Content-Security-Policy**, so even content that slips past the static check cannot
execute script or reach the network:

- A sandboxed `<iframe>` that never grants `allow-scripts`.
- CSP: `default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; script-src 'none'; base-uri 'self'; form-action 'none'`.
- Markdown is rendered to HTML with raw HTML disabled before it reaches the iframe.

This iframe/CSP boundary is the authoritative renderer-side requirement. The safe render profile
exists so authors learn about a problem inside their own run — as a typed `emit` error — instead
of discovering their report renders as inert text (or is rejected) in production.

## Determinism

A render part should be a pure function of the run's inputs so identical subjects produce
identical renders where feasible; see [REPORT.md § Determinism](REPORT.md#determinism).
LLM-driven narrative renders naturally will not be byte-identical.

## See Also

- [Report outputs](REPORT.md) — the part contract and output catalog.
- [Reporter role](../roles/REPORTER.md) — the declaration and run contract.
- [Trace](TRACE.md) — the audit record of the run that produced the render.
