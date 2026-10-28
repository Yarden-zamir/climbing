import { defineApp } from "kitshn";

// kitshn 2 (https://kit.yarden-zamir.com): a stateful singleton (one DuckDB with the club's data in /data), so only
// main deploys and there are no pull request previews. Public, as before.
export default defineApp({
  compose: {},
  deploy: [
    {
      on: "push",
      branch: "main",
      name: "prod",
      address: ["climbing.yarden-zamir.com", "onion-climbers.com", "www.onion-climbers.com"],
      startsIn: "Everyone",
    },
  ],
});
