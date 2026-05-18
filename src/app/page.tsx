"use client";

import { Check, Clock3, Copy, Moon, Plus, Sun, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { DEFAULT_KEYWORDS } from "@/lib/mediaSources";
import type { CrawlResponse, NewsCard } from "@/lib/types";

type HistoryItem = CrawlResponse & {
  id: string;
};

const HISTORY_KEY = "china-news-digest-history";

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

async function readJsonResponse(response: Response) {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    const clean = text.replace(/\s+/g, " ").trim();
    const message = clean || `服务器返回了非 JSON 响应，HTTP ${response.status}`;
    throw new Error(message.length > 400 ? `${message.slice(0, 400)}...` : message);
  }
}

function Card({ card }: { card: NewsCard }) {
  const [copied, setCopied] = useState<"url" | "body" | null>(null);
  const sourceText = card.sources.map((source) => source.source).join("、");
  const bodyText = `${card.title}\n${card.date}\n${card.summary}\n来源：${sourceText}`;

  async function copy(value: string, type: "url" | "body") {
    await navigator.clipboard.writeText(value);
    setCopied(type);
    window.setTimeout(() => setCopied(null), 1200);
  }

  return (
    <article className="news-card">
      <div className="browser-bar">
        <div className="traffic-lights" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <a className="url-pill" href={card.primaryUrl} target="_blank" rel="noreferrer">
          {card.primaryUrl}
        </a>
        <button className="icon-button" onClick={() => copy(card.primaryUrl, "url")} title="复制链接">
          {copied === "url" ? <Check size={16} /> : <Copy size={16} />}
        </button>
      </div>
      <div className="card-body">
        <button className="copy-body" onClick={() => copy(bodyText, "body")} title="复制主体文字">
          {copied === "body" ? <Check size={16} /> : <Copy size={16} />}
        </button>
        <div className="date-line">
          <Clock3 size={14} />
          {card.date}
        </div>
        <h2>{card.title}</h2>
        <p>{card.summary}</p>
        <div className="source-list">
          {card.sources.map((source) => (
            <a key={`${source.source}-${source.url}`} href={source.url} target="_blank" rel="noreferrer">
              {source.source}
            </a>
          ))}
        </div>
      </div>
    </article>
  );
}

function CardGrid({ cards }: { cards: NewsCard[] }) {
  if (cards.length === 0) {
    return <div className="empty-state">还没有新闻卡片。点击“开始”后会显示今天和昨天的相关内容。</div>;
  }

  return (
    <section className="card-grid">
      {cards.map((card) => (
        <Card key={`${card.id}-${card.primaryUrl}`} card={card} />
      ))}
    </section>
  );
}

export default function Home() {
  const [keywords, setKeywords] = useState(DEFAULT_KEYWORDS);
  const [newKeyword, setNewKeyword] = useState("");
  const [adding, setAdding] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<CrawlResponse | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [view, setView] = useState<"home" | "history">("home");
  const [dark, setDark] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(HISTORY_KEY);
    if (stored) setHistory(JSON.parse(stored));
    setDark(window.matchMedia("(prefers-color-scheme: dark)").matches);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }, [dark]);

  const groupedHistory = useMemo(() => {
    return history.reduce<Record<string, HistoryItem[]>>((groups, item) => {
      const key = item.generatedAt.slice(0, 10);
      groups[key] = groups[key] ?? [];
      groups[key].push(item);
      return groups;
    }, {});
  }, [history]);

  function persistHistory(next: HistoryItem[]) {
    setHistory(next);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
  }

  function addKeyword() {
    const value = newKeyword.trim();
    if (!value || keywords.includes(value)) return;
    setKeywords([...keywords, value]);
    setNewKeyword("");
    setAdding(false);
  }

  async function startCrawl() {
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/crawl", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ keywords })
      });
      const data = await readJsonResponse(response);
      if (!response.ok) throw new Error(data.error ?? "抓取失败");

      setResult(data);
      persistHistory([{ ...data, id: crypto.randomUUID() }, ...history].slice(0, 30));
      setView("home");
    } catch (err) {
      setError(err instanceof Error ? err.message : "抓取失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <button className="text-button" onClick={() => setView("home")}>
          今日内容
        </button>
        <button className="text-button" onClick={() => setView("history")}>
          往期内容
        </button>
        <button className="icon-button" onClick={() => setDark(!dark)} title="切换明暗模式">
          {dark ? <Sun size={18} /> : <Moon size={18} />}
        </button>
      </header>

      {view === "home" ? (
        <>
          <section className="hero">
            <h1>Hi，开始今天的工作吧！</h1>
            <div className="keyword-row">
              {keywords.map((keyword) => (
                <button
                  className="keyword-chip"
                  key={keyword}
                  onClick={() => setKeywords(keywords.filter((item) => item !== keyword))}
                  title="点击移除关键词"
                >
                  {keyword}
                  <X size={14} />
                </button>
              ))}
              {adding ? (
                <form
                  className="add-keyword-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    addKeyword();
                  }}
                >
                  <input
                    autoFocus
                    value={newKeyword}
                    onChange={(event) => setNewKeyword(event.target.value)}
                    placeholder="新关键词"
                  />
                  <button className="icon-button" type="submit" title="添加关键词">
                    <Check size={16} />
                  </button>
                </form>
              ) : (
                <button className="add-button" onClick={() => setAdding(true)} title="添加关键词">
                  <Plus size={18} />
                </button>
              )}
            </div>
            <button className="start-button" onClick={startCrawl} disabled={loading || keywords.length === 0}>
              {loading ? "抓取中..." : "开始"}
            </button>
            {error ? <p className="error-text">{error}</p> : null}
            {result ? (
              <p className="meta-text">
                已生成 {result.cards.length} 张卡片，范围：{result.window.yesterday} 至 {result.window.today}
              </p>
            ) : null}
          </section>

          <CardGrid cards={result?.cards ?? []} />
        </>
      ) : (
        <section className="history-view">
          <div className="section-heading">
            <h1>往期内容</h1>
            <button className="text-button danger" onClick={() => persistHistory([])}>
              清空
            </button>
          </div>
          {Object.entries(groupedHistory).length === 0 ? (
            <div className="empty-state">暂无往期内容。</div>
          ) : (
            Object.entries(groupedHistory).map(([date, items]) => (
              <section className="history-group" key={date}>
                <h2>{date}</h2>
                {items.map((item) => (
                  <div className="history-run" key={item.id}>
                    <div className="run-title">
                      <span>{formatTime(item.generatedAt)}</span>
                      <span>{item.cards.length} 张卡片</span>
                    </div>
                    <CardGrid cards={item.cards} />
                  </div>
                ))}
              </section>
            ))
          )}
        </section>
      )}
    </main>
  );
}
