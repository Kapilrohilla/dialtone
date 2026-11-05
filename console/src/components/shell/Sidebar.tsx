"use client";

import { BookOpen, Bot, GitBranch, History, LayoutDashboard, Plug, Radio, Settings } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { LucideIcon } from "lucide-react";
import { Chip, Menu } from "@/components/ui";
import { useLiveCalls, useLogout, useMe } from "@/lib/queries";
import { ThemeToggle } from "./ThemeToggle";
import styles from "./Sidebar.module.css";

const NAV: { href: string; label: string; Icon: LucideIcon }[] = [
  { href: "/", label: "Dashboard", Icon: LayoutDashboard },
  { href: "/agents", label: "Agents", Icon: Bot },
  { href: "/workflows", label: "Workflows", Icon: GitBranch },
  { href: "/knowledge", label: "Knowledge base", Icon: BookOpen },
  { href: "/live", label: "Live calls", Icon: Radio },
  { href: "/calls", label: "Call history", Icon: History },
  { href: "/integrations", label: "Integrations", Icon: Plug },
  { href: "/settings", label: "Settings", Icon: Settings },
];

const isActive = (pathname: string, href: string) => (href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`));

export function Sidebar() {
  const pathname = usePathname();
  const { data: me } = useMe();
  const live = useLiveCalls(10_000);
  const logout = useLogout();
  const liveCount = live.isError ? 0 : (live.data?.length ?? 0);

  return (
    <aside className={styles.sidebar}>
      <p className={styles.workspace}>{me?.workspace.name}</p>
      <nav aria-label="Main" className={styles.nav}>
        {NAV.map(({ href, label, Icon }) => {
          const active = isActive(pathname, href);
          return (
            <Link key={href} href={href} className={styles.item} aria-current={active ? "page" : undefined}>
              <Icon size={20} strokeWidth={1.75} aria-hidden="true" />
              <span className={styles.label}>{label}</span>
              {href === "/live" && liveCount >= 1 && (
                <Chip tone="blue" className={styles.count}>
                  <span className="mono">{liveCount}</span>
                </Chip>
              )}
              {href === "/integrations" && (
                <Chip tone="muted" className={styles.count}>
                  Soon
                </Chip>
              )}
            </Link>
          );
        })}
      </nav>
      <div className={styles.user}>
        <span className={styles.name}>{me?.name}</span>
        <ThemeToggle />
        <Menu label="User menu" items={[{ label: "Sign out", onSelect: () => logout.mutate() }]} />
      </div>
    </aside>
  );
}
