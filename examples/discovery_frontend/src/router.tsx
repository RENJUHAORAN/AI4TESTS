export const routes = [
  {
    path: "/login",
    name: "Login",
    component: LoginPage,
  },
  {
    path: "/home",
    name: "Home",
    component: HomePage,
  },
];

export function LoginLink() {
  return <Link to="/login">Login</Link>;
}
