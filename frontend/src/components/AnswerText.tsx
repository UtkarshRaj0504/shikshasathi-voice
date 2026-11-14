import Markdown from "react-markdown";

interface AnswerTextProps {
  /** Raw tutor answer, possibly containing light markdown (**bold**, "- " bullets, "1." steps). */
  text?: string;
  className?: string;
}

/**
 * Renders a tutor answer as safe markdown.
 *
 * Raw HTML is not enabled, so react-markdown escapes it by default (XSS-safe).
 * Links always open in a new tab with a safe rel.
 */
export function AnswerText({ text, className = "answer-text" }: AnswerTextProps) {
  return (
    <div className={className}>
      <Markdown
        components={{
          a({ node, ...props }) {
            return <a {...props} target="_blank" rel="noopener noreferrer" />;
          },
        }}
      >
        {text ?? ""}
      </Markdown>
    </div>
  );
}
