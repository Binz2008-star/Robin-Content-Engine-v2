import { API_BASE_URL, IS_DEMO_MODE, IS_CONFIG_ERROR, REQUEST_TIMEOUT_MS } from '../config';
import {
  VideoJob,
  GetJobsResponse,
  EnqueueJobRequest,
  JobActionType,
  JobActionRequest,
  JobRunRequest,
  JobRunResponse,
  ScriptGenRequest,
  GeneratedContent,
  HealthResponse,
  SystemInfoResponse,
  JobCounts,
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

// Initial demo queue data
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
    created_at: new Date(Date.now() - 3600000).toISOString(),
    updated_at: new Date(Date.now() - 3600000).toISOString(),
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
    generated_description: 'شاهد أروع أهداف إف سي 24 بتعليق إماراتي حماسي!',
    generated_tags: ['fc24', 'gaming', 'shorts', 'ريمونتادا'],
    generated_script: 'يا ساتر على هالهجمة! بالدقيقة تسعين ورأسية أسطورية بالشبك! أروع فوز باللحظة الأخيرة!',
    output_path: 'C:\\renders\\render_102.mp4',
    youtube_id: null,
    attempts: 1,
    last_error: null,
    claimed_at: new Date(Date.now() - 1800000).toISOString(),
    completed_at: new Date(Date.now() - 1500000).toISOString(),
    created_at: new Date(Date.now() - 7200000).toISOString(),
    updated_at: new Date(Date.now() - 1500000).toISOString(),
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
    generated_description: 'لقطة كوميدية ساخرة من GTA V مع تعليق إماراتي سريح!',
    generated_tags: ['gtav', 'funny', 'shorts'],
    generated_script: 'شوف شوف وين رايح بالسيارة! طار بالفضاء ونزل على شجرة! لا يطوفكم الهبوط الخرافي!',
    output_path: 'C:\\renders\\render_103.mp4',
    youtube_id: 'dQw4w9WgXcQ',
    attempts: 1,
    last_error: null,
    claimed_at: new Date(Date.now() - 10800000).toISOString(),
    completed_at: new Date(Date.now() - 9000000).toISOString(),
    created_at: new Date(Date.now() - 14400000).toISOString(),
    updated_at: new Date(Date.now() - 9000000).toISOString(),
  },
];

let demoJobs: VideoJob[] = [...INITIAL_DEMO_JOBS];

export interface RequestOptions extends RequestInit {
  timeoutMs?: number;
  maxRetries?: number;
}

/**
 * Formats user-friendly HTTP error messages.
 */
function formatHttpError(status: number, message: string): string {
  const trimmed = message ? message.trim() : '';
  switch (status) {
    case 400:
      return `Bad Request (400): ${trimmed || 'Invalid request parameters.'}`;
    case 401:
      return `Unauthorized (401): ${trimmed || 'Authentication credentials missing or invalid.'}`;
    case 403:
      return `Forbidden (403): ${trimmed || 'You do not have permission to perform this action.'}`;
    case 404:
      return `Resource Not Found (404): ${trimmed || 'The requested resource was not found.'}`;
    case 409:
      return `Conflict Error (409): ${trimmed || 'Request conflicts with current resource state.'}`;
    case 422:
      return `Validation Error (422): ${trimmed || 'Request payload failed schema validation.'}`;
    default:
      if (status >= 500) {
        return `Internal Server Error (${status}): ${trimmed || 'The server encountered an unhandled error.'}`;
      }
      return `HTTP ${status} Error: ${trimmed || 'An unexpected error occurred.'}`;
  }
}

/**
 * Base HTTP request handler with timeout, safe JSON parsing, and retry for GET.
 */
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

  const isGetMethod = method.toUpperCase() === 'GET';
  const url = `${API_BASE_URL}/${endpoint.replace(/^\//, '')}`;

  let attempt = 0;
  let lastError: Error | null = null;

  while (attempt <= (isGetMethod ? maxRetries : 0)) {
    attempt++;

    // Setup timeout AbortController
    const controller = new AbortController();
    let isTimeout = false;

    const timer = setTimeout(() => {
      isTimeout = true;
      controller.abort();
    }, timeoutMs);

    // Forward user signal abort if provided
    const handleUserAbort = () => controller.abort();
    if (userSignal) {
      if (userSignal.aborted) {
        controller.abort();
      } else {
        userSignal.addEventListener('abort', handleUserAbort);
      }
    }

    try {
      const response = await fetch(url, {
        method,
        headers: {
          'Content-Type': 'application/json',
          ...headers,
        },
        signal: controller.signal,
        ...restOptions,
      });

      clearTimeout(timer);
      if (userSignal) {
        userSignal.removeEventListener('abort', handleUserAbort);
      }

      if (!response.ok) {
        let errorBody = '';
        try {
          errorBody = await response.text();
        } catch {
          // Ignore text reading error
        }

        const formattedError = formatHttpError(response.status, errorBody);
        const apiError = new ApiError(response.status, formattedError);

        // Retry 5xx errors on GET request
        if (isGetMethod && response.status >= 500 && attempt <= maxRetries) {
          lastError = apiError;
          await new Promise((resolve) => setTimeout(resolve, attempt * 200));
          continue;
        }

        throw apiError;
      }

      // Safe JSON parsing
      try {
        const data = await response.json();
        return data as T;
      } catch (jsonErr) {
        throw new ApiError(
          response.status,
          `Invalid JSON response from server at ${endpoint}: ${jsonErr instanceof Error ? jsonErr.message : String(jsonErr)}`
        );
      }
    } catch (err) {
      clearTimeout(timer);
      if (userSignal) {
        userSignal.removeEventListener('abort', handleUserAbort);
      }

      if (err instanceof ApiError) {
        if (isGetMethod && (err.status >= 500 || err.status === 0) && attempt <= maxRetries) {
          lastError = err;
          await new Promise((resolve) => setTimeout(resolve, attempt * 200));
          continue;
        }
        throw err;
      }

      if (userSignal?.aborted && !isTimeout) {
        const abortErr = new Error('Request was cancelled by user.');
        abortErr.name = 'AbortError';
        throw abortErr;
      }

      if (isTimeout) {
        const timeoutErr = new ApiError(
          408,
          `Request timed out after ${timeoutMs}ms calling ${endpoint}`
        );
        if (isGetMethod && attempt <= maxRetries) {
          lastError = timeoutErr;
          await new Promise((resolve) => setTimeout(resolve, attempt * 200));
          continue;
        }
        throw timeoutErr;
      }

      const networkErr = new ApiError(
        0,
        `Network unavailable: Unable to reach API server at ${url}`
      );

      if (isGetMethod && attempt <= maxRetries) {
        lastError = networkErr;
        await new Promise((resolve) => setTimeout(resolve, attempt * 200));
        continue;
      }

      throw networkErr;
    }
  }

  throw lastError || new ApiError(0, `Request failed after ${maxRetries} retries.`);
}

/**
 * Calculate job counts from a list of jobs.
 */
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
    if (counts[job.status] !== undefined) {
      counts[job.status]++;
    }
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
    demoJobs = INITIAL_DEMO_JOBS.map((j) => ({ ...j }));
  },

  async getHealth(options?: RequestOptions): Promise<HealthResponse> {
    if (this.isConfigError()) {
      throw new ApiError(
        0,
        'Configuration Error: VITE_API_BASE_URL environment variable is missing in live API mode. Set VITE_API_BASE_URL or set VITE_DEMO_MODE=true.'
      );
    }

    if (this.isDemoMode()) {
      return {
        status: 'ok',
        database: 'connected (demo)',
        version: '1.0.0-demo',
        demo_mode: true,
      };
    }

    return httpRequest<HealthResponse>('/health', options);
  },

  async getJobsAndCounts(options?: RequestOptions): Promise<GetJobsResponse> {
    if (this.isConfigError()) {
      throw new ApiError(
        0,
        'Configuration Error: VITE_API_BASE_URL environment variable is missing in live API mode. Set VITE_API_BASE_URL or set VITE_DEMO_MODE=true.'
      );
    }

    if (this.isDemoMode()) {
      const copy = demoJobs.map((j) => ({ ...j }));
      return {
        jobs: copy,
        counts: calculateJobCounts(copy),
      };
    }

    const rawData = await httpRequest<GetJobsResponse | VideoJob[]>('/jobs', options);

    if (Array.isArray(rawData)) {
      return {
        jobs: rawData,
        counts: calculateJobCounts(rawData),
      };
    }

    if (rawData && Array.isArray(rawData.jobs)) {
      return {
        jobs: rawData.jobs,
        counts: rawData.counts || calculateJobCounts(rawData.jobs),
      };
    }

    return {
      jobs: [],
      counts: {
        pending: 0,
        processing: 0,
        rendered: 0,
        uploaded: 0,
        failed: 0,
        quarantined: 0,
        total: 0,
      },
    };
  },

  async getJobs(options?: RequestOptions): Promise<VideoJob[]> {
    const res = await this.getJobsAndCounts(options);
    return res.jobs;
  },

  async getJobCounts(options?: RequestOptions): Promise<JobCounts> {
    const res = await this.getJobsAndCounts(options);
    return res.counts;
  },

  async enqueueJob(
    payload: EnqueueJobRequest,
    options?: RequestOptions
  ): Promise<VideoJob> {
    if (this.isConfigError()) {
      throw new ApiError(
        0,
        'Configuration Error: VITE_API_BASE_URL environment variable is missing in live API mode. Set VITE_API_BASE_URL or set VITE_DEMO_MODE=true.'
      );
    }

    if (this.isDemoMode()) {
      const newJob: VideoJob = {
        id: Math.floor(Math.random() * 900) + 200,
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
      demoJobs = [newJob, ...demoJobs];
      return newJob;
    }

    return httpRequest<VideoJob>('/jobs', {
      method: 'POST',
      body: JSON.stringify(payload),
      ...options,
    });
  },

  async runJob(
    jobId: number | string,
    renderOnly = false,
    options?: RequestOptions
  ): Promise<JobRunResponse> {
    if (this.isConfigError()) {
      throw new ApiError(
        0,
        'Configuration Error: VITE_API_BASE_URL environment variable is missing in live API mode. Set VITE_API_BASE_URL or set VITE_DEMO_MODE=true.'
      );
    }

    if (this.isDemoMode()) {
      const numericId = Number(jobId);
      const jobIndex = demoJobs.findIndex((j) => j.id === numericId || String(j.id) === String(jobId));

      if (jobIndex !== -1) {
        const job = demoJobs[jobIndex];
        const nextStatus = renderOnly ? 'rendered' : 'uploaded';
        const updatedJob: VideoJob = {
          ...job,
          status: nextStatus,
          generated_title: job.generated_title || `${job.source_title} 🔥`,
          generated_script:
            job.generated_script ||
            'يا هلا بالشباب! شوفوا هاللقطة الأسطورية وخذينا الفوز بآخر دقيقة!',
          output_path: 'C:\\renders\\simulated_output.mp4',
          youtube_id: renderOnly ? null : 'simulated_yt_' + Date.now(),
          updated_at: new Date().toISOString(),
        };
        demoJobs[jobIndex] = updatedJob;
        return {
          status: 'success',
          message: renderOnly
            ? `Job #${jobId} rendered 9:16 video successfully (demo).`
            : `Job #${jobId} rendered and uploaded 9:16 video successfully (demo).`,
          job: updatedJob,
        };
      }
      return {
        status: 'error',
        message: `Job #${jobId} not found in demo queue.`,
        job: null,
      };
    }

    const payload: JobRunRequest = { render_only: renderOnly };

    return httpRequest<JobRunResponse>(`/jobs/${jobId}/run`, {
      method: 'POST',
      body: JSON.stringify(payload),
      ...options,
    });
  },

  async performJobAction(
    jobId: number | string,
    action: JobActionType,
    options?: RequestOptions
  ): Promise<VideoJob> {
    if (this.isConfigError()) {
      throw new ApiError(
        0,
        'Configuration Error: VITE_API_BASE_URL environment variable is missing in live API mode. Set VITE_API_BASE_URL or set VITE_DEMO_MODE=true.'
      );
    }

    if (this.isDemoMode()) {
      const numericId = Number(jobId);
      const jobIndex = demoJobs.findIndex((j) => j.id === numericId || String(j.id) === String(jobId));

      if (jobIndex === -1) {
        throw new ApiError(404, `Job #${jobId} not found.`);
      }

      const job = demoJobs[jobIndex];

      if (action === 'retry') {
        if (job.status !== 'failed' && job.status !== 'quarantined') {
          throw new ApiError(400, `Cannot retry job #${jobId} with status '${job.status}'. Only failed or quarantined jobs can be retried.`);
        }
        const updated: VideoJob = {
          ...job,
          status: 'pending',
          last_error: null,
          attempts: 0,
          updated_at: new Date().toISOString(),
        };
        demoJobs[jobIndex] = updated;
        return updated;
      }

      if (action === 'quarantine') {
        if (job.status === 'uploaded') {
          throw new ApiError(400, `Cannot quarantine uploaded job #${jobId}.`);
        }
        const updated: VideoJob = {
          ...job,
          status: 'quarantined',
          last_error: job.last_error || 'Manually quarantined by operator.',
          updated_at: new Date().toISOString(),
        };
        demoJobs[jobIndex] = updated;
        return updated;
      }

      throw new ApiError(400, `Unsupported action '${action}'.`);
    }

    const payload: JobActionRequest = { action };

    return httpRequest<VideoJob>(`/jobs/${jobId}/actions`, {
      method: 'POST',
      body: JSON.stringify(payload),
      ...options,
    });
  },

  async getSystemInfo(options?: RequestOptions): Promise<SystemInfoResponse> {
    if (this.isConfigError()) {
      throw new ApiError(
        0,
        'Configuration Error: VITE_API_BASE_URL environment variable is missing in live API mode. Set VITE_API_BASE_URL or set VITE_DEMO_MODE=true.'
      );
    }

    if (this.isDemoMode()) {
      return {
        app_name: 'Robin Content Engine v2 (Demo)',
        version: '1.0.0-demo',
        python_version: '3.11.8 (simulated)',
        ffmpeg_available: true,
        deepseek_configured: true,
        youtube_authenticated: true,
        database: 'connected (simulated)',
        demo_mode: true,
      };
    }

    return httpRequest<SystemInfoResponse>('/system', options);
  },

  async generateScript(
    payload: ScriptGenRequest,
    options?: RequestOptions
  ): Promise<GeneratedContent> {
    if (this.isConfigError()) {
      throw new ApiError(
        0,
        'Configuration Error: VITE_API_BASE_URL environment variable is missing in live API mode. Set VITE_API_BASE_URL or set VITE_DEMO_MODE=true.'
      );
    }

    if (this.isDemoMode()) {
      return {
        title: `${payload.game_name} - ${payload.topic} 🔥`,
        description: `شاهد أفضل لحظات ${payload.game_name} مع تعليق إماراتي حماسي وسريع!`,
        tags: [
          payload.game_name.toLowerCase().replace(/\s+/g, '_'),
          'gaming',
          'shorts',
          'قيمنق',
        ],
        script: `يا مرحبا بالجميع! اليوم مع لقطة حماسية من ${payload.game_name}. ${payload.topic}، وبأفضل أسلوب تعليق! شوف النهاية ولا تفوت الفوز الأسطوري!`,
      };
    }

    return httpRequest<GeneratedContent>('/script/generate', {
      method: 'POST',
      body: JSON.stringify(payload),
      ...options,
    });
  },
};
