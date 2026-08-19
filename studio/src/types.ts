export * from './api/contracts';
import { GeneratedContent } from './api/contracts';

export type ScriptData = GeneratedContent;

export type StudioTab = 'overview' | 'queue' | 'script' | 'schema';

export type ConnectionStatus = 'connecting' | 'connected' | 'demo_mode' | 'offline';
