import { NextResponse } from "next/server";
import { currentWindow, mergeArticles, summarizeWithOpenAI } from "@/lib/crawlWorkflow";
import type { CandidateArticle, CrawlResponse } from "@/lib/types";

export const runtime = "nodejs";
export const maxDuration = 60;

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as {
      keywords?: string[];
      candidates?: CandidateArticle[];
      window?: CrawlResponse["window"];
    };
    const keywords = (body.keywords ?? []).map((item) => item.trim()).filter(Boolean);
    const candidates = body.candidates ?? [];
    const window = body.window ?? currentWindow();

    const filtered = await summarizeWithOpenAI(candidates, keywords);
    const cards = mergeArticles(filtered);

    return NextResponse.json({
      generatedAt: new Date().toISOString(),
      window: {
        today: window.today,
        yesterday: window.yesterday
      },
      cards
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Summarize failed.";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
