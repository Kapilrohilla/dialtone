import { redirect } from "next/navigation";

// The console has no landing page of its own; later tasks route "/" to the dashboard.
export default function Home() {
  redirect("/sign-in");
}
