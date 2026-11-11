import { Fragment, type ReactNode } from "react";

/**
 * Small, safe Markdown for chat replies: paragraphs, headings, lists, code blocks,
 * **bold**, *italic*, `code` and links. Builds React elements (never raw HTML).
 */
export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith("```")) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) code.push(lines[i++]);
      i++;
      blocks.push(
        <pre key={blocks.length} className="md-code">
          <code>{code.join("\n")}</code>
        </pre>,
      );
      continue;
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      blocks.push(
        <p key={blocks.length} className="md-h">
          {inline(heading[2])}
        </p>,
      );
      i++;
      continue;
    }
    if (/^\s*([-*•]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*([-*•]|\d+[.)])\s+/, ""));
        i++;
      }
      const List = ordered ? "ol" : "ul";
      blocks.push(
        <List key={blocks.length}>
          {items.map((it, n) => (
            <li key={n}>{inline(it)}</li>
          ))}
        </List>,
      );
      continue;
    }
    if (!line.trim()) {
      i++;
      continue;
    }
    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !lines[i].startsWith("```") &&
      !/^(#{1,4})\s/.test(lines[i]) &&
      !/^\s*([-*•]|\d+[.)])\s+/.test(lines[i])
    ) {
      para.push(lines[i++]);
    }
    blocks.push(
      <p key={blocks.length}>
        {para.map((l, n) => (
          <Fragment key={n}>
            {n > 0 && <br />}
            {inline(l)}
          </Fragment>
        ))}
      </p>,
    );
  }
  return <div className="md">{blocks}</div>;
}

const TOKEN = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^)\s]+\)|https?:\/\/[^\s)]+|\*[^*\s][^*]*\*)/g;

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(TOKEN)) {
    const t = m[0];
    if (m.index! > last) out.push(text.slice(last, m.index));
    const k = out.length;
    if (t.startsWith("**")) out.push(<strong key={k}>{t.slice(2, -2)}</strong>);
    else if (t.startsWith("`")) out.push(<code key={k}>{t.slice(1, -1)}</code>);
    else if (t.startsWith("[")) {
      const [, label, href] = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(t) ?? [];
      out.push(
        <a key={k} href={href} target="_blank" rel="noreferrer noopener">
          {label}
        </a>,
      );
    } else if (t.startsWith("http")) {
      out.push(
        <a key={k} href={t} target="_blank" rel="noreferrer noopener">
          {t}
        </a>,
      );
    } else out.push(<em key={k}>{t.slice(1, -1)}</em>);
    last = m.index! + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
