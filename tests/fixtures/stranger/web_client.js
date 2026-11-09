// Stranger-test shape: a browser client with a hardcoded GitHub token.
const token = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ012345";

export async function whoami() {
  const response = await fetch("https://api.github.com/user", {
    headers: { Authorization: token },
  });
  return response.json();
}
