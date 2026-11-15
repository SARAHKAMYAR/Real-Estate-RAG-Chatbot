export const MAX_HISTORY_MESSAGES = 12;
export const MAX_HISTORY_CONTENT = 8000;

export function boundedHistory(history) {
  const recent = history.slice(-MAX_HISTORY_MESSAGES).map(turn => ({
    role: turn.role,
    content: turn.content.slice(0, MAX_HISTORY_CONTENT),
  }));
  while (recent.length && recent[0].role !== "user") recent.shift();
  while (recent.length > 2 && new TextEncoder().encode(JSON.stringify(recent)).length > 100000) {
    recent.splice(0, 2);
  }
  return recent;
}

export function safeUrl(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password;
  } catch { return false; }
}

export function errorMessage(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map(e => e.msg || "Invalid input").join("; ");
  return "The assistant could not answer. Please try again.";
}
