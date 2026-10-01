import { API_BASE_URL, IS_DEMO_MODE } from '../config';
import {
  VideoJob,
  EnqueueJobRequest,
  ScriptGenRequest,
  GeneratedContent,
  WorkerRunResponse,
  HealthResponse,
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

// In-memory demo queue storage when VITE_DEMO_MODE is explicitly true
let demoJobs: VideoJob[] = [
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
    generated_tags: ['gtav', 'gaming', 'funny', 'shorts'],
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

async function request<T>(
  endpoint: string,
  options: RequestInit & { signal?: AbortSignal } = {}
): Promise<T> {
  const url = `${API_BASE_URL.replace(/\/$/, '')}${endpoint}`;
  try {
    const response = await fetch(url, {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
      ...options,
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new ApiError(
        response.status,
        `API error (${response.status}): ${errorText || response.statusText}`
      );
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (error instanceof Error && error.name === 'AbortError') {
      throw error;
    }
    throw new Error(
      `Network failure calling ${endpoint}: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export const apiClient = {
  isDemoMode(): boolean {
    return IS_DEMO_MODE;
  },

  async getHealth(options?: { signal?: AbortSignal }): Promise<HealthResponse> {
    if (IS_DEMO_MODE) {
      return {
        status: 'ok',
        database: 'connected (demo)',
        version: '1.0.0-demo',
        demo_mode: true,
      };
    }
    return request<HealthResponse>('/health', options);
  },

  async getJobs(options?: { signal?: AbortSignal }): Promise<VideoJob[]> {
    if (IS_DEMO_MODE) {
      return [...demoJobs];
    }
    return request<VideoJob[]>('/jobs', options);
  },

  async getJobCounts(options?: { signal?: AbortSignal }): Promise<JobCounts> {
    const jobs = await this.getJobs(options);
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
  },

  async enqueueJob(
    payload: EnqueueJobRequest,
    options?: { signal?: AbortSignal }
  ): Promise<VideoJob> {
    if (IS_DEMO_MODE) {
      const newJob: VideoJob = {
        id: Math.floor(Math.random() * 900) + 200,
        source_path: payload.source_path || null,
        source_url: payload.source_url || null,
        source_title: payload.source_title,
        rights_confirmed: payload.rights_confirmed,
        rights_note: payload.rights_note || null,
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

    return request<VideoJob>('/jobs', {
      method: 'POST',
      body: JSON.stringify(payload),
      ...options,
    });
  },

  async generateScript(
    payload: ScriptGenRequest,
    options?: { signal?: AbortSignal }
  ): Promise<GeneratedContent> {
    if (IS_DEMO_MODE) {
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

    return request<GeneratedContent>('/script/generate', {
      method: 'POST',
      body: JSON.stringify(payload),
      ...options,
    });
  },

  async runWorker(
    renderOnly = false,
    options?: { signal?: AbortSignal }
  ): Promise<WorkerRunResponse> {
    if (IS_DEMO_MODE) {
      const pendingJobIndex = demoJobs.findIndex((j) => j.status === 'pending');
      if (pendingJobIndex !== -1) {
        const job = demoJobs[pendingJobIndex];
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
        demoJobs[pendingJobIndex] = updatedJob;
        return {
          status: 'success',
          message: renderOnly
            ? 'Worker rendered 9:16 video successfully (simulated).'
            : 'Worker rendered and uploaded 9:16 video successfully (simulated).',
          job: updatedJob,
        };
      }
      return {
        status: 'idle',
        message: 'No pending jobs in queue to process.',
        job: null,
      };
    }

    return request<WorkerRunResponse>('/worker/run-once', {
      method: 'POST',
      body: JSON.stringify({ render_only: renderOnly }),
      ...options,
    });
  },
};
