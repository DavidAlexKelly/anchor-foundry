/**
 * What p.11's walkthrough says about *this* repository (§431).
 *
 * > "…a step-by-step walkthrough that guides you through the core
 * > functionalities available in your Code Repository."
 *
 * The core functionalities, in the order somebody meets them: what ref you are
 * looking at, where the files are, that nothing is in the repository until you
 * commit, what publishing does, and where a change gets reviewed. Seven of
 * them, and **every one names a control that is already on the screen** —
 * `walkthrough.ts` drops any whose control is not there, so this list is what
 * the application *could* explain rather than what it always will.
 *
 * **Separate from the steps' machinery for the reason `repository-commands.ts`
 * is separate from `command-palette.ts`**: the arithmetic is general and the
 * words are this application's, and a test about the words should not be able
 * to break the arithmetic.
 */

import type { Step } from "./walkthrough";

export const STEPS: Step[] = [
  {
    id: "ref",
    anchor: "ref",
    title: "Everything here is at one ref",
    body:
      "The branch picker decides what the whole application is showing — the " +
      "tree, the editor, the publish plan. Switching it is how you look at " +
      "somebody else's work without touching your own.",
  },
  {
    id: "commands",
    anchor: "commands",
    title: "F1 reaches everything",
    body:
      "The command palette lists what this page can do — switch branch, open " +
      "a file, jump to a tab — and it opens with F1 from anywhere except " +
      "inside the editor, where the editor keeps its own.",
  },
  {
    id: "tabs",
    anchor: "tabs",
    title: "The tabs are the shape of the work",
    body:
      "What is in the repository (Files), what happened to it (History), what " +
      "else it could be (Branches), and what it does to this project " +
      "(Publish). Pull requests and Checks are where a change is reviewed.",
  },
  {
    id: "tree",
    tab: "files",
    anchor: "tree",
    title: "Your files, at this ref",
    body:
      "Transforms are declared by their header comments: an output dataset " +
      "and the inputs it reads. Opening a file puts it in the editor and in " +
      "the address bar, so the file you are looking at is a link.",
  },
  {
    id: "drafts",
    tab: "files",
    anchor: "drafts",
    title: "Edits live in this browser until you commit",
    body:
      "Typing changes nothing in the repository. Drafts are kept per branch " +
      "and survive a reload, and the status bar says how many are waiting — " +
      "but a colleague sees none of it until there is a commit.",
  },
  {
    id: "publish",
    tab: "publish",
    anchor: "publish",
    title: "Publishing is what makes code run",
    body:
      "A commit is a record; publishing turns the transforms it declares into " +
      "this project's definitions. The source is copied into a version, so " +
      "deleting the branch afterwards changes nothing about what runs.",
  },
  {
    id: "gate",
    tab: "publish",
    anchor: "gate",
    needs: "gated",
    title: "This project reviews code before it runs",
    body:
      "A commit is not published directly here. It is proposed, read, and " +
      "applying the proposal is what publishes it — which is also what moves " +
      "the default branch to it.",
  },
  {
    id: "pulls",
    tab: "pulls",
    anchor: "pulls",
    title: "A review is a request to publish",
    body:
      "When a project requires review, a commit is not published directly: it " +
      "is proposed, read line by line, and applying the proposal is what " +
      "publishes it and moves the default branch.",
  },
];
