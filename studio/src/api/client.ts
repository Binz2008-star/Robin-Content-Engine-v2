import {
  API_BASE_URL,
  IS_CONFIG_ERROR,
  IS_DEMO_MODE,
  REQUEST_TIMEOUT_MS,
} from '../config';
import {
  EnqueueJobRequest,
  GeneratedContent,
  GetJobsResponse,
  HealthResponse,
  JobActionRequest,
  JobActionType,
  JobCounts,
  JobRunRequest,
  JobRunResponse,
  ScriptGenRequest,
  SystemInfoResponse,
  VideoJob,
} from './contracts';

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export interface RequestOptions extends RequestInit {
  timeoutMs?: number;
  maxRetries?: number;
}

const INITIAL_DEMO_JOBS: VideoJob[] = [
  {
    id: 101,
    source_path: 'C:\\media\\gameplay_fortnite_01.mp4',
    source_url: null,
    source_title: 'Fortnite Solo Victory Clutch',
    rights_confirmed: true,
    rights_note: 'Recorded by Robin Life & Gaming',
    status: 'pending',
    generated_title: null,
    generated_description: null,
    generated_tags: [],
    generated_script: null,
    output_path: null,
    youtube_id: null,
    attempts: 0,
    last_error: null,
    claimed_at: null,
    completed_at: null,
    created_at: new Date(Date.now() - 3_600_000).toISOString(),
    updated_at: new Date(Date.now() - 3_600_000).toISOString(),
  },
  {
    id: 102,
    source_path: 'C:\\media\\fc24_comeback.mp4',
    source_url: null,
    source_title: 'FC24 90th Min Winner',
    rights_confirmed: true,
    rights_note: 'Recorded by Robin Life & Gaming',
    status: 'rendered',
    generated_title: 'ريمونتادا أسطورية في الدقيقة 90! ⚽🔥',
    generated_description:
      'شاهد أروع أهداف إف سي 24 بتعليق إماراتي حماسي!',
    generated_tags: ['fc24', 'gaming', 'shorts', 'ريمونتادا'],
    generated_script:
      'يا ساتر على هالهجمة! بالدقيقة تسعين ورأسية أسطورية بالشبك!',
    output_path: 'C:\\renders\\render_102.mp4',
    youtube_id: null,
    attempts: 1,
    last_error: null,
    claimed_at: new Date(Date.now() - 1_800_000).toISOString(),
    completed_at: new Date(Date.now() - 1_500_000).toISOString(),
    created_at: new Date(Date.now() - 7_200_000).toISOString(),
    updated_at: new Date(Date.now() - 1_500_000).toISOString(),
  },
  {
    id: 103,
    source_path: 'C:\\media\\gta_stunt_fail.mp4',
    source_url: null,
    source_title: 'GTA V Stunt Ramp Fail',
    rights_confirmed: true,
    rights_note: 'Recorded by Robin Life & Gaming',
    status: 'uploaded',
    generated_title: 'أغبى حركة في قراند 5!! 😂🚗',
    generated_description:
      'لقطة كوميدية من GTA V مع تعليق إماراتي.',
    generated_tags: ['gtav', 'funny', 'shorts'],
    generated_script:
      'شوف وين رايح بالسيارة! طار بالفضاء ونزل على شجرة!',
    output_path: 'C:\\renders\\render_103.mp4',
    youtube_id: 'demo-youtube-id',
    attempts: 1,
    last_error: null,
    claimed_at: new Date(Date.now() - 10_800_000).toISOString(),
    completed_at: new Date(Date.now() - 9_000_000).toISOString(),
    created_at: new Date(Date.now() - 14_400_000).toISOString(),
    updated_at: new Date(Date.now() - 9_000_000).toISOString(),
  },
];

let demoJobs: VideoJob[] = INITIAL_DEMO_JOBS.map((job) => ({ ...job }));

function configurationError(): ApiError {
  return new ApiError(
    0,
    'Configuration Error: VITE_API_BASE_URL is missing in live API mode. Set VITE_API_BASE_URL or explicitly set VITE_DEMO_MODE=true.'
  );
}

function formatHttpError(status: number, message: string): string {
  const detail = message.trim();
  const fallback = detail || 'The request could not be completed.';

  switch (status) {
    case 400:
      return `Bad Request (400): ${fallback}`;
    case 401:
      return `Unauthorized (401): ${fallback}`;
    case 403:
      return `Forbidden (403): ${fallback}`;
    case 404:
      return `Resource Not Found (404): ${fallback}`;
    case 409:
      return `Conflict Error (409): ${fallback}`;
    case 422:
      return `Validation Error (422): ${fallback}`;
    default:
      if (status >= 500) {
        return `Internal Server Error (${status}): ${fallback}`;
      }
      return `HTTP ${status} Error: ${fallback}`;
  }
}

async function waitBeforeRetry(attempt: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, attempt * 200));
}

async function httpRequest<T>(
  endpoint: string,
  options: RequestOptions = {}
): Promise<T> {
  const {
    timeoutMs = REQUEST_TIMEOUT_MS,
    maxRetries = 2,
    method = 'GET',
    headers,
    signal: userSignal,
    ...restOptions
  } = options;

  const normalizedMethod = method.toUpperCase();
  const isGet = normalizedMethod === 'GET';
  const allowedRetries = isGet ? maxRetries : 0;
  const url = `${API_BASE_URL}/${endpoint.replace(/^\//, '')}`;
  const mergedHeaders = {
    'Content-Type': 'application/json',
    ...headers,
  };

  let lastError: ApiError | null = null;

  for (let attempt = 0; attempt <= allowedRetries; attempt += 1) {
    const controller = new AbortController();
    let timedOut = false;

    const onUserAbort = () => controller.abort();
    if (userSignal?.aborted) {
      controller.abort();
    } else {
      userSignal?.addEventListener('abort', onUserAbort, { once: true });
    }

    const timeoutHandle = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);

    try {
      const response = await fetch(url, {
        ...restOptions,
        method: normalizedMethod,
        headers: mergedHeaders,
        signal: controller.signal,
      });

      if (!response.ok) {
        let body = '';
        try {
          body = await response.text();
        } catch {
          body = '';
        }

        const error = new ApiError(
          response.status,
          formatHttpError(response.status, body)
        );

        if (isGet && response.status >= 500 && attempt < allowedRetries) {
          lastError = error;
          await waitBeforeRetry(attempt + 1);
          continue;
        }

        throw error;
      }

      try {
        return (await response.json()) as T;
      } catch {
        throw new ApiError(
          response.status,
          `Invalid JSON response from server at ${endpoint}.`
        );
      }
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }

      if (userSignal?.aborted && !timedOut) {
        const abortError = new Error('Request was cancelled by user.');
        abortError.name = 'AbortError';
        throw abortError;
      }

      const apiError = timedOut
        ? new ApiError(
            408,
            `Request timed out after ${timeoutMs}ms calling ${endpoint}.`
          )
        : new ApiError(
            0,
            `Network unavailable: Unable to reach API server at ${url}.`
          );

      if (isGet && attempt < allowedRetries) {
        lastError = apiError;
        await waitBeforeRetry(attempt + 1);
        continue;
      }

      throw apiError;
    } finally {
      clearTimeout(timeoutHandle);
      userSignal?.removeEventListener('abort', onUserAbort);
    }
  }

  throw lastError ?? new ApiError(0, 'Request failed.');
}

export function calculateJobCounts(jobs: VideoJob[]): JobCounts {
  const counts: JobCounts = {
    pending: 0,
    processing: 0,
    rendered: 0,
    uploaded: 0,
    failed: 0,
    quarantined: 0,
    total: jobs.length,
  };

  for (const job of jobs) {
    counts[job.status] += 1;
  }

  return counts;
}

export const apiClient = {
  isDemoMode(): boolean {
    return IS_DEMO_MODE;
  },

  isConfigError(): boolean {
    return IS_CONFIG_ERROR;
  },

  resetDemoData(): void {
    demoJobs = INITIAL_DEMO_JOBS.map((job) => ({ ...job }));
  },

  async getHealth(options?: RequestOptions): Promise<HealthResponse> {
    if (this.isConfigError()) {
      throw configurationError();
    }

    if (this.isDemoMode()) {
      return {
        status: 'ok',
        database: 'demo-only',
        version: '1.0.0-demo',
        demo_mode: true,
      };
    }

    return httpRequest<HealthResponse>('/health', options);
  },

  async getJobsAndCounts(options?: RequestOptions): Promise<GetJobsResponse> {
    if (this.isConfigError()) {
      throw configurationError();
    }

    if (this.isDemoMode()) {
      const jobs = demoJobs.map((job) => ({ ...job }));
      return { jobs, counts: calculateJobCounts(jobs) };
    }

    const response = await httpRequest<GetJobsResponse | VideoJob[]>(
      '/jobs',
      options
    );

    if (Array.isArray(response)) {
      return {
        jobs: response,
        counts: calculateJobCounts(response),
      };
    }

    if (!response || !Array.isArray(response.jobs)) {
      throw new ApiError(500, 'Invalid jobs response from backend.');
    }

    return {
      jobs: response.jobs,
      counts: response.counts ?? calculateJobCounts(response.jobs),
    };
  },

  async getJobs(options?: RequestOptions): Promise<VideoJob[]> {
    return (await this.getJobsAndCounts(options)).jobs;
  },

  async getJobCounts(options?: RequestOptions): Promise<JobCounts> {
    return (await this.getJobsAndCounts(options)).counts;
  },

  async enqueueJob(
    payload: EnqueueJobRequest,
    options?: RequestOptions
  ): Promise<VideoJob> {
    if (this.isConfigError()) {
      throw configurationError();
    }

    if (this.isDemoMode()) {
      const job: VideoJob = {
        id: Math.max(200, ...demoJobs.map((item) => item.id + 1)),
        source_path: payload.source_path?.trim() || null,
        source_url: payload.source_url?.trim() || null,
        source_title: payload.source_title.trim(),
        rights_confirmed: payload.rights_confirmed,
        rights_note: payload.rights_note?.trim() || null,
        status: 'pending',
        generated_title: null,
        generated_description: null,
        generated_tags: [],
        generated_script: null,
        output_path: null,
        youtube_id: null,
        attempts: 0,
        last_error: null,
        claimed_at: null,
        completed_at: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      demoJobs = [job, ...demoJobs];
      return job;
    }

    return httpRequest<VideoJob>('/jobs', {
      ...options,
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async runJob(
    jobId: number | string,
    renderOnly = false,
    options?: RequestOptions
  ): Promise<JobRunResponse> {
    if (this.isConfigError()) {
      throw configurationError();
    }

    if (this.isDemoMode()) {
      const index = demoJobs.findIndex(
        (job) => String(job.id) === String(jobId)
      );

      if (index < 0) {
        return {
          status: 'error',
          message: `Job #${jobId} was not found in the demo queue.`,
          job: null,
        };
      }

      const current = demoJobs[index];
      const updated: VideoJob = {
        ...current,
        status: renderOnly ? 'rendered' : 'uploaded',
        generated_title:
          current.generated_title || `[DEMO] ${current.source_title}`,
        generated_script:
          current.generated_script ||
          'هذا تعليق تجريبي داخل وضع العرض فقط.',
        output_path: 'C:\\renders\\simulated_output.mp4',
        youtube_id: renderOnly ? null : `demo_${Date.now()}`,
        updated_at: new Date().toISOString(),
      };

      demoJobs[index] = updated;
      return {
        status: 'success',
        message: renderOnly
          ? `Job #${jobId} rendered in demo mode.`
          : `Job #${jobId} rendered and simulated as uploaded in demo mode.`,
        job: updated,
      };
    }

    const payload: JobRunRequest = { render_only: renderOnly };
    return httpRequest<JobRunResponse>(`/jobs/${jobId}/run`, {
      ...options,
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async performJobAction(
    jobId: number | string,
    action: JobActionType,
    options?: RequestOptions
  ): Promise<VideoJob> {
    if (this.isConfigError()) {
      throw configurationError();
    }

    if (this.isDemoMode()) {
      const index = demoJobs.findIndex(
        (job) => String(job.id) === String(jobId)
      );

      if (index < 0) {
        throw new ApiError(404, `Job #${jobId} was not found.`);
      }

      const current = demoJobs[index];
      let updated: VideoJob;

      if (action === 'retry') {
        if (
          current.status !== 'failed' &&
          current.status !== 'quarantined'
        ) {
          throw new ApiError(
            400,
            'Only failed or quarantined jobs can be retried.'
          );
        }

        updated = {
          ...current,
          status: 'pending',
          attempts: 0,
          last_error: null,
          updated_at: new Date().toISOString(),
        };
      } else {
        if (current.status === 'uploaded') {
          throw new ApiError(400, 'Uploaded jobs cannot be quarantined.');
        }

        updated = {
          ...current,
          status: 'quarantined',
          last_error:
            current.last_error || 'Manually quarantined by the operator.',
          updated_at: new Date().toISOString(),
        };
      }

      demoJobs[index] = updated;
      return updated;
    }

    const payload: JobActionRequest = { action };
    return httpRequest<VideoJob>(`/jobs/${jobId}/actions`, {
      ...options,
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async getSystemInfo(options?: RequestOptions): Promise<SystemInfoResponse> {
    if (this.isConfigError()) {
      throw configurationError();
    }

    if (this.isDemoMode()) {
      return {
        app_name: 'Robin Content Engine v2 (Demo)',
        version: '1.0.0-demo',
        python_version: 'backend required',
        ffmpeg_available: false,
        deepseek_configured: false,
        youtube_authenticated: false,
        database: 'demo-only',
        demo_mode: true,
      };
    }

    return httpRequest<SystemInfoResponse>('/system', options);
  },

  async generateScript(
    payload: ScriptGenRequest,
    _options?: RequestOptions
  ): Promise<GeneratedContent> {
    if (this.isConfigError()) {
      throw configurationError();
    }

    if (!this.isDemoMode()) {
      throw new ApiError(
        501,
        'Script generation backend endpoint is not implemented yet.'
      );
    }

    return {
      title: `[DEMO] ${payload.game_name}: ${payload.topic} 🔥`,
      description:
        'Simulated preview generated locally in Demo Mode. No backend AI request was made.',
      tags: [
        payload.game_name.toLowerCase().replace(/\s+/g, '_'),
        'gaming',
        'shorts',
        'demo',
      ],
      script: `هذا نص تجريبي فقط: ${payload.topic} في ${payload.game_name}. لم يتم الاتصال بخدمة ذكاء اصطناعي حقيقية.`,
    };
  },
};
