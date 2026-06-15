# Render Artifact

The **render** is the single file inside a [report](REPORT.md) that platform UI surfaces embed — an episode page, a
report viewer, a digest. A report's `manifest.json` points at it with the `render` field:

```json
{
  "reporter_id": "paint-arena-summarizer",
  "render": "summary.html"
}
```

`render` is optional and names at most one entry, which must be a `.md` or `.html` file in the zip. A report with no
`render` entry is still valid — it just has nothing to embed.

## Why this needs a contract

Reporters are author-supplied containers. Their output is **untrusted**: a coworld author could, deliberately or
accidentally, emit a render entry that runs JavaScript, phones home with a tracking pixel, or redirects the page. The
platform embeds that file in a first-party surface, so the render entry needs a contract that is safe to embed even when
the author is adversarial.

The contract is **defense in depth**: a safe authoring profile that producers follow and `coworld certify` enforces,
*plus* a sandboxed rendering boundary the platform always applies. Neither layer is trusted alone.

## Safe Render Profile (producer side)

The render entry must be **bundle-contained**: it may reference files packaged in the same report zip, but it must not
load resources from the network. `coworld certify` statically checks every declared render entry and fails the
certification — listing each violation — if the entry breaks the profile.

### Markdown (`.md`) — recommended default

Markdown is the simplest safe render format. The platform renders it with a CommonMark renderer that has **raw HTML
disabled**: any embedded HTML is escaped to visible text rather than parsed. That makes Markdown safe by construction, so
`coworld certify` accepts any UTF-8 Markdown render entry. Use Markdown unless you need layout or inline charts Markdown
cannot express.

### HTML (`.html`) — for rich reports

An HTML render entry may use tables, inline styles, linked same-zip stylesheets, same-zip images, same-zip script files,
and inline SVG for charts, but it must obey these rules. `coworld certify` rejects any entry that:

| Rule | Rejected examples |
| --- | --- |
| **No inline/event-handler scripting.** | Inline `<script>...</script>`, `on*` handler attributes (`onclick`, `onload`, ...), `href="javascript:..."` |
| **No embedding or navigation sinks.** | `<iframe>`, `<frame>`, `<object>`, `<embed>`, `<applet>`, `<form>`, `<base>`, `<meta http-equiv>` |
| **No automatic external loads.** Resource URLs (`src`, `srcset`, `poster`, `background`, `data`, `xlink:href`, stylesheet `href`) must be inline `data:` payloads, `#` fragments, or relative paths present in the same report zip. | `<img src="https://tracker.example/p.gif">`, `<img src="/local/path.png">`, `<link rel="stylesheet" href="https://example.com/report.css">` |
| **No unsafe CSS.** `<style>` blocks and `style=` attributes must not contain `javascript:`, `expression(`, `@import`, or `url()` pointing anywhere but a `data:` payload, `#` fragment, or relative same-zip file. | `style="background:url(https://x/y.png)"`, `@import url(...)` |

What this leaves you: text and structural elements, headings, lists, tables, inline `<style>` and `style=` attributes,
linked same-zip CSS, same-zip images, same-zip script files, and `<svg>` charts. Hyperlinks (`<a href>`) may point at
`http(s)`/`mailto` targets — they navigate only when a user clicks them; only script-bearing schemes are rejected.
Platform surfaces may render script files inertly depending on their iframe sandbox/CSP; use JavaScript only as an
optional enhancement, not as the only way to see the report.

> **Bundle-contained means bundle-contained.** Because external resource URLs are rejected, an HTML render entry carries
> its own CSS, images, scripts, and fonts in the report zip or as `data:` payloads. This keeps reports reproducible,
> embeddable offline, and free of phone-home vectors. `<img src="data:image/svg+xml,...">` is allowed even for SVG:
> browsers do not execute scripts in SVG loaded through `<img>`. Inline `<svg>...</svg>` in the document body *is*
> scanned for scripting, because inline SVG can carry it.

## Rendering Contract (platform side)

The static check is fast author-facing feedback, not the security boundary. Any platform surface that renders a report
entry must embed it inside a **sandboxed iframe** served under a strict **Content-Security-Policy**, so even an entry that
slips past the static check cannot execute script or reach the network:

- `<iframe sandbox>` **without** `allow-scripts` or `allow-same-origin`.
- CSP: `default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; script-src 'none'; base-uri 'self'; form-action 'none'`.
- Markdown is rendered to HTML with raw HTML disabled before it reaches the iframe.

This iframe/CSP boundary is the authoritative renderer-side requirement. The safe render profile exists so authors learn
about a problem at `coworld certify` time instead of discovering their report renders as inert text (or is rejected) in
production.

## Determinism

A render entry should be a pure function of the [episode bundle](EPISODE_BUNDLE.md) so identical episodes produce
identical renders; see [REPORT.md § Determinism](REPORT.md#determinism). Bundling resources in the report zip rather
than fetching them at render time is part of what makes this achievable.

## See Also

- [Report artifact](REPORT.md) — the zip that carries the render entry.
- [Reporter role](../roles/REPORTER.md) — produces the report and is exercised by `coworld certify`.
- [Episode bundle](EPISODE_BUNDLE.md) — the reporter's input.
