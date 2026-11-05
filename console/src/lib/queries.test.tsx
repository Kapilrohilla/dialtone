import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { Toast } from "@/components/ui";
import { agent, agentListItem, knowledgeDoc, workflow } from "@/test/fixtures";
import { testQueryClient } from "@/test/render";
import { server } from "@/test/server";
import { agentKey, agentsKey, useSaveDoc, useSaveWorkflow } from "./queries";

/** A client holding fresh agent data, so an invalidation is visible as `isInvalidated`. */
function setup() {
  const qc = testQueryClient();
  qc.setQueryData(agentsKey, [agentListItem]);
  qc.setQueryData(agentKey(agent.id), agent);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <Toast>{children}</Toast>
    </QueryClientProvider>
  );
  const invalidated = () => [qc.getQueryState(agentsKey)?.isInvalidated, qc.getQueryState(agentKey(agent.id))?.isInvalidated];
  return { qc, wrapper, invalidated };
}

describe("saves that change agents' older-version flags", () => {
  it("saving knowledge refreshes the agent list and every open agent", async () => {
    server.use(http.patch("*/api/knowledge/7", () => HttpResponse.json({ ...knowledgeDoc, used_by: 0 })));
    const { wrapper, invalidated } = setup();
    const { result } = renderHook(() => useSaveDoc(knowledgeDoc.id), { wrapper });
    expect(invalidated()).toEqual([false, false]);
    await result.current.mutateAsync({ body_md: "New text" });
    expect(invalidated()).toEqual([true, true]);
  });

  it("saving a workflow's graph refreshes the agent list and every open agent", async () => {
    server.use(http.patch("*/api/workflows/2", () => HttpResponse.json(workflow)));
    const { wrapper, invalidated } = setup();
    const { result } = renderHook(() => useSaveWorkflow(workflow.id), { wrapper });
    expect(invalidated()).toEqual([false, false]);
    await result.current.mutateAsync({ graph: workflow.graph });
    expect(invalidated()).toEqual([true, true]);
  });
});
