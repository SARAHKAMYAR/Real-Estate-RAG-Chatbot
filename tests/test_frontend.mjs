import { test } from "node:test";
import assert from "node:assert/strict";
import { boundedHistory, safeUrl, errorMessage } from "../app/static/history.mjs";

test("30 exchanges stay inside API limits, including long answers", () => {
  let history = [];
  for (let i = 0; i < 30; i++) {
    assert.ok(history.length <= 12);
    assert.ok(history.every(t => t.content.length <= 8000));
    history = boundedHistory([...history, {role: "user", content: `Question ${i}`},
      {role: "assistant", content: "answer ".repeat(2000)}]);
  }
  assert.equal(history.length, 12);
  assert.equal(history[0].content, "Question 24");
});

test("Unicode history stays within the request byte budget", () => {
  const history = Array.from({length: 12}, (_, i) => ({
    role: i % 2 ? "assistant" : "user", content: "🌏".repeat(4000),
  }));
  const result = boundedHistory(history);
  assert.ok(new TextEncoder().encode(JSON.stringify(result)).length <= 100000);
  assert.equal(result[0].role, "user");
});

test("only HTTP and HTTPS source links are clickable", () => {
  for (const bad of [null, "javascript:alert(1)", "data:text/html,x", "//evil.test", "https://a:b@example.org"])
    assert.equal(safeUrl(bad), false);
  assert.equal(safeUrl("https://www.government.nl/"), true);
});

test("API validation errors are readable", () => {
  assert.equal(errorMessage([{msg: "Message is too long"}]), "Message is too long");
  assert.equal(errorMessage("Please retry"), "Please retry");
});
