// The docs are read where they are, in the release's files (see scripts/release.mjs): nothing is copied by hand.
import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { TREE } from './lib/site';

const docs = defineCollection({
  loader: glob({
    base: TREE,
    pattern: ['README.md', 'CHANGELOG.md', 'docs/**/*.md'],
    generateId: ({ entry }) => entry, // the repository path, e.g. docs/CLI.md
  }),
});

export const collections = { docs };
