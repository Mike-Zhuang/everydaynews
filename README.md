# everydaynews
Crawl news on the topics of embodied AI, clips, geopolitics, robotics in China based on a fixed list of media.

## Vercel deployment

This is a Next.js app. Vercel should use the Next.js framework preset and the default output directory. Do not set the Output Directory to `public`; `public` is only for static assets and is not the build output for this app.

Required environment variables:

```text
OPENAI_API_KEY=your_gateway_token
OPENAI_BASE_URL=https://api.gptoai.top
OPENAI_MODEL=gpt-5.4
```

`OPENAI_API_KEY` should be the relay/gateway token value only, without the `Bearer ` prefix. `OPENAI_BASE_URL` defaults to `https://api.gptoai.top` if omitted. `OPENAI_MODEL` should match a model name supported by the relay service.
