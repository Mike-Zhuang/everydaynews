import { NextResponse } from "next/server";
import { collectCandidatesFromSource, currentWindow, candidatesToCards } from "@/lib/crawlWorkflow";
import { MEDIA_SOURCES } from "@/lib/mediaSources";

export const runtime = "nodejs";
export const maxDuration = 20;

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as { index?: number };
    const index = typeof body.index === "number" && Number.isInteger(body.index) ? body.index : -1;
    const source = index >= 0 ? MEDIA_SOURCES[index] : undefined;

    if (!source) {
      return NextResponse.json({ error: "Invalid media source index." }, { status: 400 });
    }

    const window = currentWindow();
    const candidates = await collectCandidatesFromSource(source.url, source.name, window.valid);

    return NextResponse.json({
      generatedAt: new Date().toISOString(),
      window: {
        today: window.today,
        yesterday: window.yesterday
      },
      source: {
        index,
        name: source.name,
        url: source.url
      },
      candidates,
      cards: candidatesToCards(candidates)
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Source search failed.";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
