"use client";

import { StateBlock, Table, Td, Th } from "@/components/ui";
import { TopBar } from "@/components/shell/TopBar";
import { usePhoneNumbers } from "@/lib/queries";
import styles from "../settings.module.css";

export default function PhoneNumbersPage() {
  const numbers = usePhoneNumbers();
  return (
    <>
      <TopBar title="Phone numbers" />
      <div className={styles.tableWrap}>
        {numbers.isError ? (
          <StateBlock state="error" title="Couldn't reach the call server." onRetry={() => numbers.refetch()} />
        ) : numbers.isPending ? (
          <StateBlock state="loading" title="Loading" />
        ) : numbers.data.length === 0 ? (
          <StateBlock state="empty" title="No numbers found on the call server." />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>Number</Th>
                  <Th>Line</Th>
                  <Th>Answered by</Th>
                </tr>
              </thead>
              <tbody>
                {numbers.data.map((n) => (
                  <tr key={n.number}>
                    <Td className={styles.monoText}>{n.number}</Td>
                    <Td>{n.trunk_name}</Td>
                    <Td>{n.agent_name ?? <span className={styles.mutedText}>No agent</span>}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <p className={styles.tableNote}>Numbers are set up by your admin.</p>
          </>
        )}
      </div>
    </>
  );
}
