import { Search } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { Button, Field } from "@/components/ui";
import { OUTCOME_GROUPS } from "@/lib/outcomes";
import { useAgents, type CallFilters } from "@/lib/queries";
import styles from "../calls.module.css";

const DEBOUNCE_MS = 300;

/** A text value that commits to the URL 300ms after typing stops. It adopts the URL's value only when that was
 *  changed elsewhere (Clear filters, back button), never for the echo of its own commit, so keystrokes typed while
 *  the URL catches up are kept. */
function useDebouncedText(urlValue: string, commit: (value: string) => void) {
  const [text, setText] = useState(urlValue);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const committed = useRef(urlValue);
  const latest = useRef(commit);
  latest.current = commit;
  useEffect(() => {
    if (urlValue === committed.current) return;
    clearTimeout(timer.current);
    committed.current = urlValue;
    setText(urlValue);
  }, [urlValue]);
  useEffect(() => () => clearTimeout(timer.current), []);
  return {
    text,
    type(value: string) {
      setText(value);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        committed.current = value.trim();
        latest.current(committed.current);
      }, DEBOUNCE_MS);
    },
  };
}

export type FiltersProps = {
  filters: CallFilters;
  anyFilter: boolean;
  /** The server's words for a bad filter. */
  error: string | null;
  onChange: (patch: Partial<CallFilters>, mode?: "push" | "replace") => void;
  onClear: () => void;
};

export function Filters({ filters, anyFilter, error, onChange, onClear }: FiltersProps) {
  const { data: agents } = useAgents();
  const searchId = useId();
  const [more, setMore] = useState(Boolean(filters.mood || filters.city));
  const search = useDebouncedText(filters.q ?? "", (q) => onChange({ q }, "replace"));
  const mood = useDebouncedText(filters.mood ?? "", (v) => onChange({ mood: v }, "replace"));
  const city = useDebouncedText(filters.city ?? "", (v) => onChange({ city: v }, "replace"));

  return (
    <section aria-label="Filters" className={styles.filters}>
      <div className={styles.filterRow}>
        <div className={styles.search}>
          <label htmlFor={searchId} className={styles.searchLabel}>Phone number</label>
          <div className={styles.searchBox}>
            <Search size={18} strokeWidth={1.75} aria-hidden="true" />
            <input
              id={searchId}
              type="search"
              placeholder="Search by phone number"
              value={search.text}
              onChange={(e) => search.type(e.target.value)}
            />
          </div>
        </div>
        <Field
          control="select"
          label="Outcome"
          className={styles.select}
          value={filters.outcome}
          onChange={(e) => onChange({ outcome: e.target.value })}
        >
          <option value="">Any outcome</option>
          {OUTCOME_GROUPS.map((g) => (
            <option key={g} value={g}>{g}</option>
          ))}
        </Field>
        <Field control="select" label="Agent" className={styles.select} value={filters.agent} onChange={(e) => onChange({ agent: e.target.value })}>
          <option value="">Any agent</option>
          {[...(agents ?? [])]
            .sort((a, b) => a.name.localeCompare(b.name))
            .map((a) => (
              <option key={a.id} value={String(a.id)}>{a.name}</option>
            ))}
        </Field>
        <Button variant="outline" aria-expanded={more} onClick={() => setMore((v) => !v)}>More filters</Button>
        {anyFilter && <Button variant="text" onClick={onClear}>Clear filters</Button>}
      </div>
      {more && (
        <div className={styles.filterRow}>
          <Field label="Mood" className={styles.text} value={mood.text} onChange={(e) => mood.type(e.target.value)} />
          <Field label="City" className={styles.text} value={city.text} onChange={(e) => city.type(e.target.value)} />
        </div>
      )}
      {error && <p role="alert" className={styles.filterError}>{error}</p>}
    </section>
  );
}
