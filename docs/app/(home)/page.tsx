import Link from 'next/link';

export default function HomePage() {
  return (
    <main className="flex flex-col justify-center items-center text-center flex-1 px-4 py-16 gap-6">
      <h1 className="text-4xl font-bold">Dialtone</h1>
      <p className="max-w-xl text-fd-muted-foreground">
        Self-hosted AI voice agents that answer your phone line. LiveKit for media and SIP, a Python agent
        worker, a Django API and a Next.js console to build, test and watch your agents.
      </p>
      <div className="flex gap-3">
        <Link
          href="/docs/getting-started/quickstart"
          className="rounded-md bg-fd-primary px-4 py-2 text-sm font-medium text-fd-primary-foreground"
        >
          Quickstart
        </Link>
        <Link href="/docs" className="rounded-md border px-4 py-2 text-sm font-medium">
          Documentation
        </Link>
      </div>
    </main>
  );
}
