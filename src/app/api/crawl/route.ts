import * as cheerio from "cheerio";
import { NextResponse } from "next/server";
import { MEDIA_SOURCES } from "@/lib/mediaSources";
import type { CrawlResponse, NewsCard } from "@/lib/types";

export const runtime = "nodejs";
export const maxDuration = 60;

type CandidateArticle = {
  title: string;
  url: string;
  source: string;
  date: string;
  text: string;
};

type OpenAIArticle = {
  title: string;
  date: string;
  summary: string;
  source: string;
  url: string;
  canonicalKey: string;
};

const REQUEST_TIMEOUT_MS = 10000;
const MAX_LINKS_PER_SOURCE = 8;
const MAX_CANDIDATES_FOR_OPENAI = 80;
const DEFAULT_OPENAI_BASE_URL = "https://api.gptoai.top";
const DEFAULT_OPENAI_MODEL = "gpt-4o-mini";
const USER_AGENT =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36";

function dateKey(date: Date) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(date);
}

function currentWindow() {
  const now = new Date();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  return {
    today: dateKey(now),
    yesterday: dateKey(yesterday),
    valid: new Set([dateKey(now), dateKey(yesterday)])
  };
}

async function fetchHtml(url: string) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(url, {
      signal: controller.signal,
      headers: {
        "user-agent": USER_AGENT,
        accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8"
      },
      redirect: "follow"
    });

    if (!response.ok) return null;
    const contentType = response.headers.get("content-type") ?? "";
    if (!contentType.includes("text/html") && !contentType.includes("application/xhtml+xml")) {
      return null;
    }

    return response.text();
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

function normalizeUrl(href: string, baseUrl: string) {
  try {
    const resolved = new URL(href, baseUrl);
    if (!["http:", "https:"].includes(resolved.protocol)) return null;
    resolved.hash = "";
    return resolved.toString();
  } catch {
    return null;
  }
}

function extractLinks(html: string, baseUrl: string) {
  const $ = cheerio.load(html);
  const links: { title: string; url: string }[] = [];
  const seen = new Set<string>();

  $("a[href]").each((_, element) => {
    const href = $(element).attr("href");
    const title = $(element).text().replace(/\s+/g, " ").trim();
    if (!href || title.length < 6) return;
    const url = normalizeUrl(href, baseUrl);
    if (!url || seen.has(url)) return;
    if (/\.(jpg|jpeg|png|gif|webp|svg|pdf|zip)$/i.test(url)) return;
    seen.add(url);
    links.push({ title, url });
  });

  return links.slice(0, MAX_LINKS_PER_SOURCE);
}

function parseDate(raw?: string | null) {
  if (!raw) return null;
  const clean = raw.replace(/\s+/g, " ").trim();
  const isoMatch = clean.match(/20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}/);
  if (!isoMatch) return null;
  const normalized = isoMatch[0].replace(/[年月/.]/g, "-").replace(/日/g, "");
  const parsed = new Date(normalized);
  if (Number.isNaN(parsed.getTime())) return null;
  return dateKey(parsed);
}

function extractArticle(html: string, fallbackTitle: string, url: string, source: string) {
  const $ = cheerio.load(html);
  $("script, style, noscript, nav, footer, header, aside").remove();

  const title =
    $("meta[property='og:title']").attr("content") ||
    $("h1").first().text() ||
    $("title").text() ||
    fallbackTitle;

  const date =
    parseDate($("meta[property='article:published_time']").attr("content")) ||
    parseDate($("meta[name='pubdate']").attr("content")) ||
    parseDate($("meta[name='publishdate']").attr("content")) ||
    parseDate($("time[datetime]").first().attr("datetime")) ||
    parseDate($("time").first().text()) ||
    parseDate($.root().text());

  const paragraphs = $("article p, main p, .article p, .content p, .post p, p")
    .map((_, p) => $(p).text().replace(/\s+/g, " ").trim())
    .get()
    .filter((line) => line.length > 20);

  const text = paragraphs.join("\n").slice(0, 3500);

  if (!date || text.length < 80) return null;

  return {
    title: title.replace(/\s+/g, " ").trim().slice(0, 180),
    url,
    source,
    date,
    text
  } satisfies CandidateArticle;
}

async function mapConcurrent<T, R>(
  items: T[],
  limit: number,
  mapper: (item: T) => Promise<R>
) {
  const results: R[] = [];
  let index = 0;

  async function worker() {
    while (index < items.length) {
      const current = items[index++];
      results.push(await mapper(current));
    }
  }

  await Promise.all(Array.from({ length: limit }, worker));
  return results;
}

async function collectCandidates(validDates: Set<string>) {
  const sourcePages = await mapConcurrent(MEDIA_SOURCES, 6, async (source) => {
    const html = await fetchHtml(source.url);
    if (!html) return [];
    return extractLinks(html, source.url).map((link) => ({ ...link, source: source.name }));
  });

  const uniqueLinks = new Map<string, { title: string; url: string; source: string }>();
  sourcePages.flat().forEach((link) => {
    if (!uniqueLinks.has(link.url)) uniqueLinks.set(link.url, link);
  });

  const articles = await mapConcurrent(Array.from(uniqueLinks.values()), 8, async (link) => {
    const html = await fetchHtml(link.url);
    if (!html) return null;
    const article = extractArticle(html, link.title, link.url, link.source);
    if (!article || !validDates.has(article.date)) return null;
    return article;
  });

  return articles.filter(Boolean).slice(0, MAX_CANDIDATES_FOR_OPENAI) as CandidateArticle[];
}

function parseOpenAIJson(text: string) {
  const fenced = text.match(/```json\s*([\s\S]*?)```/i);
  const body = fenced?.[1] ?? text;
  const parsed = JSON.parse(body);
  if (Array.isArray(parsed)) return parsed as OpenAIArticle[];
  if (Array.isArray(parsed.articles)) return parsed.articles as OpenAIArticle[];
  return [];
}

function mergeArticles(articles: OpenAIArticle[]): NewsCard[] {
  const groups = new Map<string, NewsCard>();

  for (const article of articles) {
    const key = (article.canonicalKey || article.title).toLowerCase().trim();
    const existing = groups.get(key);
    const sourceHit = { source: article.source, url: article.url };

    if (!existing) {
      groups.set(key, {
        id: key.replace(/[^a-z0-9\u4e00-\u9fa5]+/gi, "-").slice(0, 80),
        title: article.title,
        date: article.date,
        summary: article.summary,
        sources: [sourceHit],
        primaryUrl: article.url
      });
      continue;
    }

    if (article.date > existing.date) existing.date = article.date;
    if (!existing.sources.some((item) => item.url === article.url)) {
      existing.sources.push(sourceHit);
    }
  }

  return Array.from(groups.values()).sort((a, b) => b.date.localeCompare(a.date));
}

async function summarizeWithOpenAI(candidates: CandidateArticle[], keywords: string[]) {
  if (candidates.length === 0) return [];

  const apiKey = process.env.OPENAI_API_KEY?.trim();
  if (!apiKey) {
    throw new Error("Missing OPENAI_API_KEY. Add it to .env.local before crawling.");
  }

  const baseUrl = (process.env.OPENAI_BASE_URL?.trim() || DEFAULT_OPENAI_BASE_URL).replace(/\/$/, "");
  const model = process.env.OPENAI_MODEL?.trim() || DEFAULT_OPENAI_MODEL;
  const prompt = `
你是中文新闻编辑。请从候选新闻中筛选和这些关键词/主题相关的内容：${keywords.join("、")}。
只保留半导体、机器人、人工智能、中国宏观经济、以及与中国有关的地缘新闻。
每条摘要用中文，2-4 个要点句，避免营销话术。
如果多篇文章报道同一事件，给它们完全相同的 canonicalKey。
只返回 JSON 数组，不要返回解释文字。数组元素格式：
{
  "title": "标题",
  "date": "YYYY-MM-DD",
  "summary": "内容要点概括",
  "source": "新闻来源",
  "url": "新闻链接",
  "canonicalKey": "同一新闻事件的稳定短键"
}

候选新闻：
${JSON.stringify(
  candidates.map((item) => ({
    title: item.title,
    date: item.date,
    source: item.source,
    url: item.url,
    text: item.text
  }))
)}
`;

  const response = await fetch(`${baseUrl}/v1/chat/completions`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
      "User-Agent": "everydaynews/1.0"
    },
    body: JSON.stringify({
      model,
      messages: [
        {
          role: "system",
          content: "You are a precise Chinese news editor. Return valid JSON only."
        },
        {
          role: "user",
          content: prompt
        }
      ]
    })
  });

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data?.error?.message ?? `OpenAI-compatible API request failed: ${response.status}`);
  }

  const text = data?.choices?.[0]?.message?.content;
  if (typeof text !== "string") {
    throw new Error("OpenAI-compatible API returned an empty response.");
  }

  return parseOpenAIJson(text);
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as { keywords?: string[] };
    const keywords = (body.keywords ?? []).map((item) => item.trim()).filter(Boolean);
    const window = currentWindow();
    const candidates = await collectCandidates(window.valid);
    const filtered = await summarizeWithOpenAI(candidates, keywords);
    const cards = mergeArticles(filtered);

    const payload: CrawlResponse = {
      generatedAt: new Date().toISOString(),
      window: {
        today: window.today,
        yesterday: window.yesterday
      },
      cards
    };

    return NextResponse.json(payload);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Crawl failed.";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
