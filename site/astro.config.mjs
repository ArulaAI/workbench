import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import tailwindcss from '@tailwindcss/vite';
import mermaid from 'astro-mermaid';

import react from '@astrojs/react';

// https://astro.build/config
export default defineConfig({
    trailingSlash: 'always',
    vite: {
        plugins: [tailwindcss()],
    },
    integrations: [mermaid(), starlight({
        title: 'SPEED',
        // Single warm-dark theme — no light/dark toggle
        head: [
            {
                tag: 'script',
                attrs: { is: 'inline' },
                content: `document.documentElement.dataset.theme = 'dark';`,
            },
            {
                tag: 'script',
                attrs: { type: 'module' },
                content: `
                    import { initializeApp } from 'https://www.gstatic.com/firebasejs/11.4.0/firebase-app.js';
                    import { getAnalytics } from 'https://www.gstatic.com/firebasejs/11.4.0/firebase-analytics.js';
                    const app = initializeApp({
                        apiKey: "AIzaSyCZTCb3iCcRu_XhNaKSXtlzzd9Z1IoCdYI",
                        authDomain: "speed-cdc1c.firebaseapp.com",
                        projectId: "speed-cdc1c",
                        storageBucket: "speed-cdc1c.firebasestorage.app",
                        messagingSenderId: "973752787192",
                        appId: "1:973752787192:web:2de8c429169dd6531f5b0d",
                        measurementId: "G-MJLYFXBMH2"
                    });
                    getAnalytics(app);
                `,
            },
        ],
        social: [
            {
                icon: 'github',
                label: 'GitHub',
                href: 'https://github.com/speed-org/SPEED',
            },
        ],
        components: {
            SocialIcons: './src/components/Starlight/SocialLinks.astro',
        },
        sidebar: [
            {
                label: 'Tutorials',
                collapsed: true,
                items: [
                    { label: 'Installation', slug: 'docs/installation' },
                    { label: 'Getting Started', slug: 'docs/getting-started' },
                    { label: 'Running SPEED', slug: 'docs/running-speed' },
                ],
            },
            {
                label: 'How-to Guides',
                collapsed: true,
                items: [
                    { label: 'Writing High-Fidelity Specs', slug: 'docs/writing-specs' },
                    { label: 'Multi-Player Mode', slug: 'docs/multiplayer' },
                    { label: 'Custom Agent Providers', slug: 'docs/custom-providers' },
                    { label: 'Troubleshooting', slug: 'docs/troubleshooting' },
                ],
            },
            {
                label: 'Reference',
                collapsed: true,
                items: [
                    { label: 'CLI Reference', slug: 'docs/api/cli' },
                    { label: 'Pipeline Reference', slug: 'docs/api/pipeline' },
                    { label: 'Configuration', slug: 'docs/api/config' },
                    { label: 'Learning System', slug: 'docs/api/learn' },
                    { label: 'Multi-Player Reference', slug: 'docs/api/multiplayer-reference' },
                    { label: 'Technical Schemas', slug: 'docs/api/schemas' },
                    { label: 'Language Support', slug: 'docs/api/language-support' },
                    {
                        label: 'Agent Fleet',
                        collapsed: true,
                        items: [
                            { label: 'Overview', slug: 'docs/api/agents' },
                            {
                                label: 'Planning Fleet',
                                collapsed: true,
                                items: [
                                    { label: 'Architect', slug: 'docs/api/agents/architect' },
                                    { label: 'Validator', slug: 'docs/api/agents/validator' },
                                    { label: 'Plan Verifier', slug: 'docs/api/agents/plan-verifier' },
                                    { label: 'Spec Auditor', slug: 'docs/api/agents/spec-auditor' },
                                ],
                            },
                            {
                                label: 'Execution Fleet',
                                collapsed: true,
                                items: [
                                    { label: 'Developer', slug: 'docs/api/agents/developer' },
                                    { label: 'Reviewer', slug: 'docs/api/agents/reviewer' },
                                    { label: 'Product Guardian', slug: 'docs/api/agents/product-guardian' },
                                ],
                            },
                            {
                                label: 'Resilience Fleet',
                                collapsed: true,
                                items: [
                                    { label: 'Debugger', slug: 'docs/api/agents/debugger' },
                                    { label: 'Supervisor', slug: 'docs/api/agents/supervisor' },
                                    { label: 'Coherence Checker', slug: 'docs/api/agents/coherence-checker' },
                                    { label: 'Integrator', slug: 'docs/api/agents/integrator' },
                                ],
                            },
                            {
                                label: 'Security & Defect Fleet',
                                collapsed: true,
                                items: [
                                    { label: 'Security Auditor', slug: 'docs/api/agents/security-auditor' },
                                    { label: 'Triage', slug: 'docs/api/agents/triage' },
                                ],
                            },
                        ],
                    },
                ],
            },
            {
                label: 'Tooling',
                collapsed: true,
                items: [
                    { label: 'Integrated Workflow', slug: 'docs/tooling/integrated-workflow' },
                ],
            },
            {
                label: 'Architecture',
                collapsed: true,
                items: [
                    { label: 'System Overview', slug: 'docs/architecture' },
                    { label: 'SPEED: Explained', slug: 'docs/architecture/speed-explained' },
                    { label: 'Agent Orchestration', slug: 'docs/architecture/agent-orchestration' },
                    { label: 'The Context Pipeline', slug: 'docs/architecture/context-pipeline' },
                    { label: 'Technical Schemas', slug: 'docs/architecture/schemas' },
                    { label: 'Codebase Semantic Graph', slug: 'docs/codebase-semantic-graph' },
                    { label: 'Multi-Player Architecture', slug: 'docs/architecture/multiplayer' },
                ],
            },
            {
                label: 'Explanation',
                collapsed: true,
                items: [
                    { label: 'Manifesto', slug: 'docs/manifesto' },
                    { label: 'Design Philosophy', slug: 'docs/design-philosophy' },
                    { label: 'The SPEED Process', slug: 'docs/process' },
                ],
            },
        ],
        customCss: [
            '@fontsource/ibm-plex-mono/400.css',
            '@fontsource/ibm-plex-mono/600.css',
            '@fontsource/inter/400.css',
            '@fontsource/inter/600.css',
            './src/styles/starlight-custom.css',
        ],
		}), react()],
});