import "@testing-library/jest-dom";

// Mock URL.createObjectURL and URL.revokeObjectURL for tests
if (typeof window !== "undefined") {
  window.URL.createObjectURL = () => "blob:mock-url";
  window.URL.revokeObjectURL = () => {};
  window.HTMLMediaElement.prototype.play = () => Promise.resolve();
  window.HTMLMediaElement.prototype.pause = () => {};
}
