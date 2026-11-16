"use client";

import { codesOf, type OutcomeOption } from "@/lib/dispositions";
import { DISPOSITIONS, OUTCOME_GROUPS } from "@/lib/outcomes";
import { useDispositionLists } from "@/lib/queries";

/** The outcomes a workflow end step can choose: every code in the workspace's disposition lists, or the
 *  built-in codes while there are no lists. */
export function useOutcomeOptions(): OutcomeOption[] {
  const { data } = useDispositionLists();
  const codes = data ? codesOf(data) : [];
  return codes.length ? codes : DISPOSITIONS;
}

/** The <option>s of an end step's outcome select: every disposition code in the workspace's lists (the built-in
 *  codes while there are none), by report group. A saved code no list has any more stays selectable. */
export function OutcomeOptions({ value }: { value: string }) {
  const options = useOutcomeOptions();
  return (
    <>
      <option value="" disabled>Choose an outcome</option>
      {value && !options.some((d) => d.code === value) && <option value={value}>{`${value} (in no disposition list)`}</option>}
      {OUTCOME_GROUPS.map((group) => {
        const inGroup = options.filter((d) => d.group === group);
        return inGroup.length ? (
          <optgroup key={group} label={group}>
            {inGroup.map((d) => (
              <option key={d.code} value={d.code}>{d.label}</option>
            ))}
          </optgroup>
        ) : null;
      })}
    </>
  );
}
