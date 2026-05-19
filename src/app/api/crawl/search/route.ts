import { NextResponse } from "next/server";
import { candidatesToCards, collectCandidates, currentWindow } from "@/lib/crawlWorkflow";

export const runtime = "nodejs";
export const maxDuration = 45;

export async function POST() {
  try {
    const window = currentWindow();
    const candidates = await collectCandidates(window.valid);

    return NextResponse.json({
      generatedAt: new Date().toISOString(),
      window: {
        today: window.today,
        yesterday: window.yesterday
      },
      candidates,
      cards: candidatesToCards(candidates)
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Search failed.";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
