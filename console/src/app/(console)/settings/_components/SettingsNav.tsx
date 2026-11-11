"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Chip } from "@/components/ui";
import { useMe } from "@/lib/queries";
import styles from "../settings.module.css";

const GENERAL = { href: "/settings/general", label: "General" };

const LINKS = [
  { href: "/settings", label: "Profile" },
  { href: "/settings/team", label: "Team" },
  { href: "/settings/calls", label: "Call handling" },
  { href: "/settings/phone-numbers", label: "Phone numbers" },
  { href: "/settings#appearance", label: "Appearance" },
];

export function SettingsNav() {
  const pathname = usePathname();
  const { data: me } = useMe();
  // General renames the whole install: Django superusers only.
  const links = me?.is_superuser ? [LINKS[0], GENERAL, ...LINKS.slice(1)] : LINKS;
  return (
    <nav aria-label="Settings" className={styles.nav}>
      {links.map(({ href, label }) => (
        <Link key={href} href={href} className={styles.link} aria-current={href === pathname ? "page" : undefined}>
          {label}
        </Link>
      ))}
      <span className={styles.link} aria-disabled="true" data-disabled="true">
        Billing <Chip tone="muted">Soon</Chip>
      </span>
    </nav>
  );
}
