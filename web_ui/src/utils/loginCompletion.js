import { watch } from 'vue'

export const LOGIN_ROUTE = '/login'
export const AUTHENTICATED_HOME_ROUTE = '/dashboard'

export function installLoginCompletionRedirect({ store, router }) {
  return watch(
    [
      () => store.isLoggedIn,
      () => router.currentRoute.value.path,
    ],
    ([isLoggedIn, currentPath]) => {
      if (isLoggedIn && currentPath === LOGIN_ROUTE) {
        void router.replace(AUTHENTICATED_HOME_ROUTE)
      }
    },
    { immediate: true },
  )
}
