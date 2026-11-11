import { BUILTIN_EXPRESSIONS, BUILTIN_HINTS } from "@/lib/tokens";
import { http, HttpResponse } from "msw";
import { agent, agentListItem, callDetail, callPage, dashboard, instance, knowledgeDoc, liveCall, me, phoneNumbers, voices, workflow } from "@/test/fixtures";

// Default happy-path responses. Tests override with server.use(...).
export const handlers = [
  http.get("*/api/auth/csrf", () => HttpResponse.json({ detail: "ok" })),
  http.get("*/api/me", () => HttpResponse.json(me)),
  http.get("*/api/instance/", () => HttpResponse.json(instance)),
  http.get("*/api/dashboard", () => HttpResponse.json(dashboard)),
  http.get("*/api/calls", () => HttpResponse.json(callPage)),
  http.get("*/api/live", () => HttpResponse.json([liveCall])),
  http.get("*/api/calls/:room", () => HttpResponse.json(callDetail)),
  http.get("*/api/agents", () => HttpResponse.json([agentListItem])),
  http.get("*/api/agents/:id", () => HttpResponse.json(agent)),
  http.get("*/api/knowledge", () => HttpResponse.json([knowledgeDoc])),
  http.get("*/api/knowledge/:id", () => HttpResponse.json(knowledgeDoc)),
  http.get("*/api/workflows", () => HttpResponse.json([workflow])),
  http.get("*/api/workflows/:id", () => HttpResponse.json(workflow)),
  http.get("*/api/workflows/:id/suggestions/current", () => new HttpResponse(null, { status: 204 })),
  http.get("*/api/voices", () => HttpResponse.json({ pipeline: "gemini-live", voices })),
  http.get("*/api/expressions", () => HttpResponse.json(BUILTIN_EXPRESSIONS.map((name) => ({ name, hint: BUILTIN_HINTS[name], builtin: true })))),
  http.get("*/api/phone-numbers", () => HttpResponse.json(phoneNumbers)),
];
