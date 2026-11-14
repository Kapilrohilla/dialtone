"use client";

import Link from "next/link";
import { useState } from "react";
import { Field } from "@/components/ui";
import { useWorkflows } from "@/lib/queries";
import { AdvancedSection } from "./AdvancedSection";
import { AuditFixesSection, type AuditFixesSectionProps } from "./AuditFixesSection";
import { BehaviourSection } from "./BehaviourSection";
import { KnowledgeSection } from "./KnowledgeSection";
import { VersionsSection } from "./VersionsSection";
import { VoiceSection, type MarkInvalid, type PanelSectionProps } from "./VoiceSection";
import styles from "./editor.module.css";

export type SidePanelProps = PanelSectionProps &
  Pick<AuditFixesSectionProps, "beforeAccept" | "onAgentChanged"> & {
    timingsError?: string | null;
    markInvalid: MarkInvalid;
  };

/** The 320px settings column: voice, knowledge, workflow, behaviour, advanced, audit fixes, versions. */
export function SidePanel({ timingsError, markInvalid, beforeAccept, onAgentChanged, ...props }: SidePanelProps) {
  return (
    <aside aria-label="Agent settings" className={styles.side}>
      <VoiceSection {...props} markInvalid={markInvalid} />
      <KnowledgeSection {...props} />
      <WorkflowSection {...props} />
      <BehaviourSection {...props} />
      <AdvancedSection {...props} timingsError={timingsError} markInvalid={markInvalid} />
      <AuditFixesSection agent={props.agent} readOnly={props.readOnly} beforeAccept={beforeAccept} onAgentChanged={onAgentChanged} />
      <VersionsSection agentId={props.agent.id} />
    </aside>
  );
}

function WorkflowSection({ agent, readOnly, save }: PanelSectionProps) {
  const { data: workflows } = useWorkflows();
  const [workflow, setWorkflow] = useState<number | null>(agent.workflow);
  return (
    <div className={styles.panelSection}>
      <h2 className={styles.panelTitle}>Workflow</h2>
      <Field
        control="select"
        label="Workflow"
        value={workflow === null ? "" : String(workflow)}
        disabled={readOnly}
        onChange={(e) => {
          const next = e.target.value ? Number(e.target.value) : null;
          setWorkflow(next);
          void save({ workflow: next });
        }}
      >
        <option value="">None, script only</option>
        {workflows?.map((w) => (
          <option key={w.id} value={w.id}>{w.name}</option>
        ))}
      </Field>
      {workflow !== null && (
        <Link href={`/workflows/${workflow}`} className={styles.link}>Open workflow</Link>
      )}
    </div>
  );
}
