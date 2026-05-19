import * as cheerio from "cheerio";
import { MEDIA_SOURCES } from "@/lib/mediaSources";
import type { CandidateArticle, NewsCard } from "@/lib/types";

type OpenAIArticle = {
  title: string;
  date: string;
  summary: string;
  source: string;
  url: string;
  canonicalKey: string;
};

const REQUEST_TIMEOUT_MS = 3500;
const MAX_TOPICS_PER_RUN = 5;
const MAX_RESULTS_PER_ENGINE = 5;
const MAX_ARTICLE_LINKS_PER_RUN = 30;
const MAX_CANDIDATES_FOR_OPENAI = 24;
const SITE_FILTERS_PER_QUERY = 4;
const DEFAULT_OPENAI_BASE_URL = "https://api.gptoai.top";
const DEFAULT_OPENAI_MODEL = "gpt-5.4";
const USER_AGENT =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36";

type UnionSearchResult = {
  title: string;
  url: string;
  snippet: string;
  platform: string;
};

const allowedSourceHosts = MEDIA_SOURCES.map((source) => {
  try {
    return new URL(source.url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}).filter(Boolean);

const sourceNameByHost = new Map(
  MEDIA_SOURCES.flatMap((source) => {
    try {
      const host = new URL(source.url).hostname.replace(/^www\./, "");
      return [[host, source.name] as const];
    } catch {
      return [];
    }
  })
);

export function dateKey(date: Date) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(date);
}

export function currentWindow() {
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

function cleanSearchUrl(href: string, baseUrl: string) {
  const url = normalizeUrl(href, baseUrl);
  if (!url) return null;

  const parsed = new URL(url);
  const duckTarget = parsed.searchParams.get("uddg");
  if (duckTarget) return normalizeUrl(duckTarget, baseUrl);

  if (parsed.hostname.includes("bing.com") && parsed.pathname === "/ck/a") {
    return null;
  }

  return url;
}

function isUsableArticleUrl(url: string) {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.replace(/^www\./, "");
    if (!["http:", "https:"].includes(parsed.protocol)) return false;
    if (/\.(jpg|jpeg|png|gif|webp|svg|pdf|zip|mp4|mp3)$/i.test(parsed.pathname)) return false;
    if (/google|bing|duckduckgo|baidu|sogou|so\.com|javascript/i.test(parsed.hostname)) return false;
    return allowedSourceHosts.some((allowed) => host === allowed || host.endsWith(`.${allowed}`));
  } catch {
    return false;
  }
}

function sourceNameForUrl(url: string, fallback: string) {
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    const matched = allowedSourceHosts.find((allowed) => host === allowed || host.endsWith(`.${allowed}`));
    return matched ? (sourceNameByHost.get(matched) ?? fallback) : fallback;
  } catch {
    return fallback;
  }
}

function extractSearchLinks(html: string, baseUrl: string, platform: string) {
  const $ = cheerio.load(html);
  const links: UnionSearchResult[] = [];
  const seen = new Set<string>();
  const selectors =
    platform === "bing"
      ? "li.b_algo h2 a[href]"
      : platform === "duckduckgo"
        ? ".result h2 a[href], .result__title a[href]"
        : "a[href]";

  $(selectors).each((_, element) => {
    const href = $(element).attr("href");
    const title = $(element).text().replace(/\s+/g, " ").trim();
    if (!href || title.length < 6) return;
    const url = cleanSearchUrl(href, baseUrl);
    if (!url || seen.has(url) || !isUsableArticleUrl(url)) return;

    const item = $(element).closest("li, .result, .b_algo, div");
    const snippet = item.text().replace(/\s+/g, " ").trim().replace(title, "").slice(0, 260);
    seen.add(url);
    links.push({ title, url, snippet, platform });
  });

  return links.slice(0, MAX_RESULTS_PER_ENGINE);
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
    parseDate($.root().text()) ||
    dateKey(new Date());

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

export async function collectCandidates(validDates: Set<string>) {
  const searchResults = await unionSearch(Array.from(validDates));
  const uniqueLinks = new Map<string, UnionSearchResult>();
  searchResults.forEach((link) => {
    if (!uniqueLinks.has(link.url)) uniqueLinks.set(link.url, link);
  });

  const articles = await mapConcurrent(Array.from(uniqueLinks.values()).slice(0, MAX_ARTICLE_LINKS_PER_RUN), 10, async (link) => {
    const html = await fetchHtml(link.url);
    if (!html) return null;
    const article = extractArticle(html, link.title, link.url, sourceNameForUrl(link.url, `${link.platform} search`));
    if (!article || !validDates.has(article.date)) return null;
    return article;
  });

  return articles.filter(Boolean).slice(0, MAX_CANDIDATES_FOR_OPENAI) as CandidateArticle[];
}

function buildUnionQueries(validDates: string[]) {
  const topics = ["半导体", "机器人", "人工智能", "中国宏观经济", "中国 地缘政治"];
  const dateTerms = validDates.join(" OR ");
  const hostGroups: string[][] = [];
  for (let index = 0; index < allowedSourceHosts.length; index += SITE_FILTERS_PER_QUERY) {
    hostGroups.push(allowedSourceHosts.slice(index, index + SITE_FILTERS_PER_QUERY));
  }

  return topics.slice(0, MAX_TOPICS_PER_RUN).flatMap((topic) =>
    hostGroups.map((hosts) => {
      const siteFilters = hosts.map((host) => `site:${host}`).join(" OR ");
      return `${topic} 中国 新闻 (${dateTerms}) (${siteFilters})`;
    })
  );
}

async function searchDuckDuckGo(query: string) {
  const url = `https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`;
  const html = await fetchHtml(url);
  return html ? extractSearchLinks(html, url, "duckduckgo") : [];
}

async function searchBing(query: string) {
  const url = `https://www.bing.com/search?q=${encodeURIComponent(query)}`;
  const html = await fetchHtml(url);
  return html ? extractSearchLinks(html, url, "bing") : [];
}

async function searchJina(query: string) {
  try {
    const response = await fetch(`https://s.jina.ai/?q=${encodeURIComponent(query)}`, {
      headers: {
        Accept: "application/json",
        "X-Respond-With": "no-content",
        "User-Agent": USER_AGENT
      },
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS)
    });
    if (!response.ok) return [];
    const data = await response.json();
    const items = Array.isArray(data?.data) ? data.data : [];
    return items.slice(0, MAX_RESULTS_PER_ENGINE).flatMap((item: Record<string, unknown>) => {
      const title = typeof item.title === "string" ? item.title : "";
      const url = typeof item.url === "string" ? item.url : "";
      const snippet = typeof item.description === "string" ? item.description : "";
      return title && url && isUsableArticleUrl(url)
        ? [{ title, url, snippet, platform: "jina" }]
        : [];
    });
  } catch {
    return [];
  }
}

async function unionSearch(validDates: string[]) {
  const queries = buildUnionQueries(validDates);
  const batches = await Promise.all(
    queries.map(async (query) => {
      const results = await Promise.allSettled([
        searchDuckDuckGo(query),
        searchBing(query),
        searchJina(query)
      ]);
      return results.flatMap((result) => (result.status === "fulfilled" ? result.value : []));
    })
  );

  return batches.flat();
}

export function candidatesToCards(candidates: CandidateArticle[]): NewsCard[] {
  return candidates.map((article) => ({
    id: article.url,
    title: article.title,
    date: article.date,
    summary: article.text.slice(0, 220),
    sources: [{ source: article.source, url: article.url }],
    primaryUrl: article.url
  }));
}

function parseOpenAIJson(text: string) {
  const fenced = text.match(/```json\s*([\s\S]*?)```/i);
  const body = fenced?.[1] ?? text;
  const firstArrayStart = body.indexOf("[");
  const firstObjectStart = body.indexOf("{");
  const lastArrayEnd = body.lastIndexOf("]");
  const lastObjectEnd = body.lastIndexOf("}");
  const jsonText =
    firstArrayStart !== -1 && lastArrayEnd !== -1
      ? body.slice(firstArrayStart, lastArrayEnd + 1)
      : firstObjectStart !== -1 && lastObjectEnd !== -1
        ? body.slice(firstObjectStart, lastObjectEnd + 1)
        : body;

  try {
    const parsed = JSON.parse(jsonText);
    if (Array.isArray(parsed)) return parsed as OpenAIArticle[];
    if (Array.isArray(parsed.articles)) return parsed.articles as OpenAIArticle[];
    return [];
  } catch {
    throw new Error(`Model did not return valid JSON: ${clipText(body)}`);
  }
}

function clipText(value: string, maxLength = 400) {
  const clean = value.replace(/\s+/g, " ").trim();
  return clean.length > maxLength ? `${clean.slice(0, maxLength)}...` : clean;
}

function parseMaybeJson(text: string) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

export function mergeArticles(articles: OpenAIArticle[]): NewsCard[] {
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

export async function summarizeWithOpenAI(candidates: CandidateArticle[], keywords: string[]) {
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
只返回 JSON 数组，不要返回解释文字，不要 Markdown 代码块。数组元素格式：
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
      "User-Agent": "Apifox/1.0.0 (https://apifox.com)"
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

  const rawResponse = await response.text();
  const data = parseMaybeJson(rawResponse);
  if (!response.ok) {
    const message =
      data?.error?.message ??
      data?.message ??
      clipText(rawResponse) ??
      `OpenAI-compatible API request failed: ${response.status}`;
    throw new Error(`OpenAI-compatible API request failed: ${message}`);
  }
  if (!data) {
    throw new Error(`OpenAI-compatible API returned non-JSON response: ${clipText(rawResponse)}`);
  }

  const text = data?.choices?.[0]?.message?.content;
  if (typeof text !== "string") {
    throw new Error("OpenAI-compatible API returned an empty response.");
  }

  return parseOpenAIJson(text);
}
