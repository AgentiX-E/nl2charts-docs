// LlmProvider: one required method. Everything else is optional on purpose --
// a user must be able to plug in an internal gateway in ~10 lines.
export function createLlmProvider(kind, opts = {}) {
  if (typeof kind === 'object' && kind !== null) return normalize(kind);   // programmatic
  switch (kind) {
    case 'http': return createHttp(opts);
    case 'mock': return createMock(opts);
    case 'ai-sdk': return fromAiSdk(opts.model);
    default: throw new Error('UNKNOWN_LLM_PROVIDER');
  }
}

function normalize(p) {
  if (typeof p.complete !== 'function') throw new Error('LLM_PROVIDER_NEEDS_COMPLETE');
  return { id: p.id ?? 'custom', streaming: typeof p.stream === 'function', ...p };
}

export function createHttp({ baseUrl, model, apiKey, maxRetries = 2 }) {
  return normalize({
    id: 'http', streaming: false,
    async complete(req, { signal } = {}) {
      let last;
      for (let attempt = 0; attempt <= maxRetries; attempt++) {
        try {
          const res = await fetch(`${baseUrl}/v1/chat/completions`, {
            method: 'POST', signal,
            headers: { 'content-type': 'application/json', authorization: `Bearer ${apiKey}` },
            body: JSON.stringify({
              model,
              messages: [
                ...(req.system ? [{ role: 'system', content: req.system }] : []),
                ...req.messages,
              ],
              temperature: req.temperature ?? 0,
              max_tokens: req.maxTokens ?? 512,
            }),
          });
          if (res.status === 429 || res.status >= 500) {
            const e = new Error(`LLM_HTTP_${res.status}`); e.code = `LLM_HTTP_${res.status}`; e.retryable = true;
            throw e;
          }
          if (!res.ok) { const e = new Error(`LLM_HTTP_${res.status}`); e.code = `LLM_HTTP_${res.status}`; e.retryable = false; throw e; }
          const d = await res.json();
          return {
            text: d.choices[0].message.content,
            usage: { inputTokens: d.usage.prompt_tokens, outputTokens: d.usage.completion_tokens },
            model: d.model, finishReason: 'stop',
          };
        } catch (e) {
          last = e;
          if (!e.retryable || attempt === maxRetries) break;
          await new Promise((r) => setTimeout(r, 10 * (attempt + 1)));
        }
      }
      throw last;
    },
  });
}

export function createMock({ sql = 'select 1', failWith = null } = {}) {
  return normalize({
    id: 'mock',
    async complete(req) {
      if (failWith) { const e = new Error(failWith); e.code = failWith; throw e; }
      return { text: sql, usage: { inputTokens: 10, outputTokens: 5 }, model: 'mock-1', finishReason: 'stop' };
    },
  });
}

// Thin adapter: the AI SDK's LanguageModelV1 shape -> our LlmProvider.
// Proves the ecosystem is reusable without making the SDK our contract.
export function fromAiSdk(model) {
  return normalize({
    id: `ai-sdk:${model.modelId ?? 'model'}`,
    async complete(req) {
      const r = await model.doGenerate({
        prompt: [
          ...(req.system ? [{ role: 'system', content: [{ type: 'text', text: req.system }] }] : []),
          ...req.messages.map((m) => ({ role: m.role, content: [{ type: 'text', text: m.content }] })),
        ],
        temperature: req.temperature ?? 0,
        maxTokens: req.maxTokens ?? 512,
      });
      return {
        text: r.text,
        usage: { inputTokens: r.usage.promptTokens, outputTokens: r.usage.completionTokens },
        model: model.modelId ?? 'ai-sdk', finishReason: r.finishReason === 'length' ? 'length' : 'stop',
      };
    },
  });
}
