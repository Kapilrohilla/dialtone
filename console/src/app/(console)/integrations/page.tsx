"use client";

import { Cloud, Hash, ListChecks, MessageCircle, Phone, Sheet, Users, Webhook, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { Button, Chip, Table, Td, Th } from "@/components/ui";
import { TopBar } from "@/components/shell/TopBar";
import { RequestDialog } from "./_components/RequestDialog";
import styles from "./integrations.module.css";

const INTEGRATIONS: { name: string; does: string; Icon: LucideIcon }[] = [
  { name: "Google Sheets", does: "Add each call as a row", Icon: Sheet },
  { name: "Webhooks", does: "Send an event when a call ends", Icon: Webhook },
  { name: "WhatsApp Business", does: "Send details after a call", Icon: MessageCircle },
  { name: "Salesforce", does: "Update the lead with the outcome", Icon: Cloud },
  { name: "HubSpot", does: "Sync contacts and outcomes", Icon: Users },
  { name: "LeadSquared", does: "Update leads", Icon: ListChecks },
  { name: "Slack", does: "Alert a channel when a call needs a person", Icon: Hash },
  { name: "Your own phone number (SIP)", does: "Bring your existing number", Icon: Phone },
];

export default function IntegrationsPage() {
  const [asking, setAsking] = useState(false);
  return (
    <>
      <TopBar
        title="Integrations"
        primary={
          <Button variant="primary" onClick={() => setAsking(true)}>
            Request an integration
          </Button>
        }
      />
      <div className={styles.page}>
        <p className={styles.lead}>Connect your agents to the tools your team already uses. These are coming soon.</p>
        <Table rowHeight={72}>
          <thead>
            <tr>
              <Th>Integration</Th>
              <Th>What it will do</Th>
              <Th>Status</Th>
            </tr>
          </thead>
          <tbody>
            {INTEGRATIONS.map(({ name, does, Icon }) => (
              <tr key={name}>
                <Td>
                  <span className={styles.name}>
                    <Icon size={20} strokeWidth={1.75} aria-hidden="true" />
                    {name}
                  </span>
                </Td>
                <Td>{does}</Td>
                <Td>
                  <Chip tone="muted">Coming soon</Chip>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </div>
      <RequestDialog open={asking} onClose={() => setAsking(false)} />
    </>
  );
}
