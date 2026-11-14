import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AnswerText } from "../components/AnswerText";

describe("AnswerText", () => {
  it("renders markdown emphasis and bullets with no literal asterisks visible", () => {
    const answer = "**Photosynthesis** is important.\n\n* Plants use sunlight\n* They make food";
    const { container } = render(<AnswerText text={answer} />);

    // Bold becomes a <strong> element.
    const strong = container.querySelector("strong");
    expect(strong).not.toBeNull();
    expect(strong?.textContent).toBe("Photosynthesis");

    // "* " bullets become list items.
    const items = container.querySelectorAll("li");
    expect(items.length).toBe(2);
    expect(items[0].textContent).toBe("Plants use sunlight");

    // No raw markdown symbols leak into the rendered output.
    expect(container.textContent).not.toContain("*");
    expect(container.innerHTML).not.toContain("**");
  });

  it("opens links in a new tab with a safe rel", () => {
    render(<AnswerText text="See [the docs](https://example.com)." />);
    const link = screen.getByRole("link", { name: "the docs" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("does not render raw HTML from the answer", () => {
    const { container } = render(
      <AnswerText text={'<img src="x" onerror="alert(1)" /> hello'} />
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("hello");
  });

  it("renders Hindi and Kannada text correctly", () => {
    render(<AnswerText text={"**प्रकाश संश्लेषण** क्या है?\n\n- **ವಿಜ್ಞಾನ** ಎಂದರೇನು"} />);
    expect(screen.getByText("प्रकाश संश्लेषण")).toBeInTheDocument();
    expect(screen.getByText("ವಿಜ್ಞಾನ")).toBeInTheDocument();
  });
});
