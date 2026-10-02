import { notifyUnauthorized } from '../lib/auth'
import { readNdjson } from './ndjson'
import type {
  AppSettings, Health, PartialEnrichment, ReviewPhrase, ReviewQueue, WordEnrichment,
  Book, BookChapter, BookDetail, FeedItem, GutenbergResult, Media, NewsFeed, MediaDetail, MediaUpdates, PartialExplanation, PartialFeedback, RootResult, SavedPhrase, SentenceExplanation, ShadowFeedback,
  AdminDisk, AdminUsage, AdminUser, Invite, User,
  PodcastChannel, PodcastLookup, PodcastShow, ShadowRecording, TtsStatus, WordResult,
} from './types'

/** Calls that may answer 401 as part of their job (a wrong password) do not send the learner back to the login page. */
const OWN_401 = /^\/auth\/(login|register|me)$/

/** A 401 means the login ended (or never happened): the app shows the login page. */
function checkLoggedIn(res: Response, path = ''): void {
  if (res.status === 401 && !OWN_401.test(path)) notifyUnauthorized()
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api${path}`, {
      headers: typeof init?.body === 'string' ? { 'Content-Type': 'application/json' } : undefined,
      ...init,
    })
  } catch {
    throw new Error('連不上後端，請確認已啟動 fastapi（port 8000）')
  }
  checkLoggedIn(res, path)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail ?? `請求失敗（${res.status}）`)
  }
  return res.json()
}

/** Why a streaming call was refused: the server's own words when it gave any (a daily limit says which and until when). */
async function streamFailure(res: Response): Promise<Error> {
  if (res.status === 401) return new Error('請先登入')
  const body = await res.json().catch(() => null)
  return new Error(typeof body?.detail === 'string' ? body.detail : `請求失敗（${res.status}）`)
}

const post = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) })

type ExplainEvent =
  | { type: 'queued'; position: number }
  | { type: 'partial'; data: PartialExplanation }
  | { type: 'done'; data: SentenceExplanation }
  | { type: 'error'; message: string }

/** Ask for a sentence explanation and receive it as it is written. Resolves with the final answer.
 * `onQueued` hears how many jobs are ahead while the request waits for its turn. */
export async function streamExplain(
  sentence: string,
  context: string,
  onPartial: (partial: PartialExplanation) => void,
  signal: AbortSignal,
  onQueued?: (ahead: number) => void,
): Promise<SentenceExplanation> {
  let res: Response
  try {
    res = await fetch('/api/ai/explain-sentence/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sentence, context }),
      signal,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new Error('連不上後端，請確認已啟動 fastapi（port 8000）')
  }
  checkLoggedIn(res)
  if (!res.ok || !res.body) throw await streamFailure(res)
  for await (const event of readNdjson<ExplainEvent>(res.body)) {
    if (event.type === 'queued') onQueued?.(event.position)
    else if (event.type === 'partial') onPartial(event.data)
    else if (event.type === 'done') return event.data
    else throw new Error(event.message)
  }
  throw new Error('連線中斷，請再試一次')
}

type FeedbackEvent =
  | { type: 'partial'; data: PartialFeedback }
  | { type: 'done'; data: ShadowFeedback }
  | { type: 'error'; message: string }

/** The AI's comments on one recording, received as they are written. Resolves with the final text. */
export async function streamFeedback(
  recordingId: number,
  onPartial: (partial: PartialFeedback) => void,
  signal: AbortSignal,
): Promise<ShadowFeedback> {
  let res: Response
  try {
    res = await fetch(`/api/recordings/${recordingId}/feedback/stream`, { method: 'POST', signal })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new Error('連不上後端，請確認已啟動 fastapi（port 8000）')
  }
  checkLoggedIn(res)
  if (!res.ok || !res.body) throw await streamFailure(res)
  for await (const event of readNdjson<FeedbackEvent>(res.body)) {
    if (event.type === 'partial') onPartial(event.data)
    else if (event.type === 'done') return event.data
    else throw new Error(event.message)
  }
  throw new Error('連線中斷，請再試一次')
}

/** A book paragraph's translation, received as it is written. Resolves with the final text. */
export async function streamParagraphTranslation(paragraphId: number, onPartial: (text: string) => void, signal: AbortSignal): Promise<string> {
  let res: Response
  try {
    res = await fetch(`/api/books/paragraphs/${paragraphId}/translate/stream`, { method: 'POST', signal })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new Error('連不上後端，請確認已啟動 fastapi（port 8000）')
  }
  checkLoggedIn(res)
  if (!res.ok || !res.body) throw await streamFailure(res)
  for await (const event of readNdjson<{ type: 'partial' | 'done' | 'error'; text?: string; message?: string }>(res.body)) {
    if (event.type === 'partial') onPartial(event.text ?? '')
    else if (event.type === 'done') return event.text ?? ''
    else throw new Error(event.message)
  }
  throw new Error('連線中斷，請再試一次')
}

/** The AI's extra explanation of a word, received as it is written. Resolves with the final version. */
export async function streamWordEnrichment(word: string, onPartial: (partial: PartialEnrichment) => void, signal: AbortSignal): Promise<WordEnrichment> {
  let res: Response
  try {
    res = await fetch(`/api/dictionary/${encodeURIComponent(word)}/enrich/stream`, { method: 'POST', signal })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new Error('連不上後端，請確認已啟動 fastapi（port 8000）')
  }
  checkLoggedIn(res)
  if (!res.ok || !res.body) throw await streamFailure(res)
  for await (const event of readNdjson<{ type: 'partial' | 'done' | 'error'; data?: PartialEnrichment; message?: string }>(res.body)) {
    if (event.type === 'partial') onPartial(event.data ?? {})
    else if (event.type === 'done') return event.data as WordEnrichment
    else throw new Error(event.message)
  }
  throw new Error('連線中斷，請再試一次')
}

/** The natural voice's audio for a short text, as an address the player can use (release it with URL.revokeObjectURL). */
/** What may be changed on the settings page. A key that is left out stays as it is; '' clears it. */
export interface SettingsPatch {
  llm_model?: string
  whisper_model?: string
  llm_backend?: 'ollama' | 'cloud'
  cloud_base_url?: string
  cloud_api_key?: string
  cloud_model?: string
  stt_backend?: 'local' | 'cloud'
  stt_base_url?: string
  stt_api_key?: string
  stt_model?: string
  fallback_local?: boolean
}

export async function fetchSpeech(text: string, voice: string): Promise<string> {
  let res: Response
  try {
    res = await fetch('/api/tts/speak', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, voice }) })
  } catch {
    throw new Error('連不上後端，請確認已啟動 fastapi（port 8000）')
  }
  checkLoggedIn(res)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail ?? `語音產生失敗（${res.status}）`)
  }
  return URL.createObjectURL(await res.blob())
}

export const mediaAudioUrl = (mediaId: number) => `/api/media/${mediaId}/audio`
export const sentenceAudioUrl = (segmentId: number) => `/api/segments/${segmentId}/audio`
export const recordingAudioUrl = (recordingId: number) => `/api/recordings/${recordingId}/audio`

export const api = {
  me: () => request<User>('/auth/me'),
  login: (username: string, password: string) => request<User>('/auth/login', post({ username, password })),
  register: (code: string, username: string, password: string) => request<User>('/auth/register', post({ code, username, password })),
  logout: () => request<{ ok: boolean }>('/auth/logout', { method: 'POST' }),
  adminUsers: () => request<AdminUser[]>('/admin/users'),
  setUserDisabled: (id: number, disabled: boolean) => request<{ id: number; disabled: boolean }>(`/admin/users/${id}/${disabled ? 'disable' : 'enable'}`, { method: 'POST' }),
  adminUsage: () => request<AdminUsage>('/admin/usage'),
  adminDisk: () => request<AdminDisk>('/admin/disk'),
  adminInvites: () => request<Invite[]>('/admin/invites'),
  createInvite: (days = 7) => request<Invite>('/admin/invites', post({ days })),
  listMedia: (kind?: 'video' | 'podcast') => request<Media[]>(`/media${kind ? `?kind=${kind}` : ''}`),
  getMedia: (id: number) => request<MediaDetail>(`/media/${id}`),
  getUpdates: (id: number, known: number, missingFrom: number) =>
    request<MediaUpdates>(`/media/${id}/updates?known=${known}&missing_from=${missingFrom}`),
  /** Tell the translator which sentence the learner is at; it works on the ones around it first. */
  setFocus: (id: number, idx: number) => request<{ ok: boolean }>(`/media/${id}/focus`, post({ idx })),
  testConnection: (target: 'llm' | 'stt') => request<{ ok: boolean; message: string }>(`/settings/test/${target}`, { method: 'POST' }),
  ttsStatus: () => request<TtsStatus>('/tts/status'),
  health: () => request<Health>('/health'),
  getSettings: () => request<AppSettings>('/settings'),
  updateSettings: (patch: SettingsPatch) =>
    request<AppSettings>('/settings', { method: 'PUT', body: JSON.stringify(patch) }),
  reviewQueue: (limit = 20) => request<ReviewQueue>(`/phrases/review?limit=${limit}`),
  reviewPhrase: (id: number, grade: 0 | 1 | 2 | 3) => request<ReviewPhrase>(`/phrases/${id}/review`, post({ grade })),
  listBooks: (kind: 'book' | 'news' = 'book') => request<Book[]>(`/books?kind=${kind}`),
  listFeeds: () => request<NewsFeed[]>('/news/feeds'),
  addFeed: (url: string) => request<NewsFeed>('/news/feeds', post({ url })),
  deleteFeed: (id: number) => request<{ ok: boolean }>(`/news/feeds/${id}`, { method: 'DELETE' }),
  feedItems: (id: number) => request<FeedItem[]>(`/news/feeds/${id}/items`),
  addArticle: (url: string) => request<Book>('/news/articles', post({ url })),
  /** Difficulty level (0 basic … 4 rare) for each known word, for colouring a text. */
  wordLevels: (words: string[]) => request<{ levels: Record<string, number> }>('/dictionary/levels', post({ words })),
  searchGutenberg: (q: string) => request<GutenbergResult[]>(`/books/search?q=${encodeURIComponent(q)}`),
  addGutenbergBook: (id: number) => request<Book>('/books/gutenberg', post({ id })),
  uploadBook: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<Book>('/books/upload', { method: 'POST', body: form })
  },
  getBook: (id: number) => request<BookDetail>(`/books/${id}`),
  getChapter: (bookId: number, idx: number) => request<BookChapter>(`/books/${bookId}/chapters/${idx}`),
  saveBookProgress: (bookId: number, chapter: number, paragraph: number) =>
    request<{ ok: boolean }>(`/books/${bookId}/progress`, { method: 'PUT', body: JSON.stringify({ chapter, paragraph }) }),
  deleteBook: (id: number) => request<{ ok: boolean }>(`/books/${id}`, { method: 'DELETE' }),

  lookUpPodcast: (url: string) => request<PodcastLookup>(`/podcasts/feed?url=${encodeURIComponent(url)}`),
  listChannels: () => request<PodcastChannel[]>('/podcasts/channels'),
  followChannel: (url: string) => request<PodcastChannel>('/podcasts/channels', post({ url })),
  unfollowChannel: (id: number) => request<{ ok: boolean }>(`/podcasts/channels/${id}`, { method: 'DELETE' }),
  channelEpisodes: (id: number) => request<PodcastShow>(`/podcasts/channels/${id}/episodes`),
  addPodcast: (p: { audio_url: string; title?: string; thumbnail?: string; duration?: number }) => request<Media>('/podcasts', post(p)),
  uploadPodcast: (file: File, title = '') => {
    const form = new FormData()
    form.append('file', file)
    form.append('title', title)
    return request<Media>('/podcasts/upload', { method: 'POST', body: form })
  },
  createMedia: (url: string) => request<Media>('/media', post({ url })),
  retryMedia: (id: number) => request<Media>(`/media/${id}/retry`, { method: 'POST' }),
  deleteMedia: (id: number) => request<{ ok: boolean }>(`/media/${id}`, { method: 'DELETE' }),

  getWord: (word: string) => request<WordResult>(`/dictionary/${encodeURIComponent(word)}`),
  getRootWords: (root: string, meaning = '') =>
    request<RootResult>(`/dictionary/root/${encodeURIComponent(root)}?meaning=${encodeURIComponent(meaning)}`),


  uploadRecording: (segmentId: number, audio: Blob) => {
    const form = new FormData()
    form.append('file', audio, 'recording.webm')
    return request<ShadowRecording>(`/segments/${segmentId}/recordings`, { method: 'POST', body: form })
  },
  listRecordings: (segmentId: number) => request<ShadowRecording[]>(`/segments/${segmentId}/recordings`),
  deleteRecording: (id: number) => request<{ ok: boolean }>(`/recordings/${id}`, { method: 'DELETE' }),

  listPhrases: (q = '') => request<SavedPhrase[]>(`/phrases?q=${encodeURIComponent(q)}`),
  savePhrase: (p: Partial<SavedPhrase> & { text: string }) => request<SavedPhrase>('/phrases', post(p)),
  deletePhrase: (id: number) => request<{ ok: boolean }>(`/phrases/${id}`, { method: 'DELETE' }),
}
