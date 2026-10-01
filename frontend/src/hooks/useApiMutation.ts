import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/lib/api";

type HttpMethod = "post" | "put" | "delete";

interface UseApiMutationOptions<TData, TVariables> {
  /** HTTP method (default: "post") */
  method?: HttpMethod;
  /** Query keys to invalidate after a successful mutation */
  invalidates?: string[][];
  /** Custom success message. Pass false to suppress the toast. */
  successMessage?: string | false;
  /** Custom error message override. If omitted, uses the thrown error message. */
  errorMessage?: string;
  /** Called after the server responds successfully (before invalidation) */
  onSuccess?: (data: TData, variables: TVariables) => void | Promise<void>;
  /** Called after error */
  onError?: (error: Error, variables: TVariables) => void;
}

/**
 * Thin TanStack wrapper around api.post / api.put / api.delete.
 *
 * Usage:
 *   const approve = useApiMutation<void, string>({
 *     invalidates: [["api", "/posts?limit=100"]],
 *     successMessage: "Post approved",
 *   });
 *   <button disabled={approve.isPending} onClick={() => approve.mutate(`/posts/${id}/approve`)}>
 *
 * The mutate() argument is the URL path (string) or [path, body] tuple.
 */
export function useApiMutation<TData = unknown, TVariables = string>(
  options: UseApiMutationOptions<TData, TVariables> = {}
) {
  const queryClient = useQueryClient();
  const {
    method = "post",
    invalidates = [],
    successMessage,
    errorMessage,
    onSuccess,
    onError,
  } = options;

  const mutation = useMutation<TData, Error, TVariables>({
    mutationFn: async (variables: TVariables) => {
      const [path, body] = Array.isArray(variables)
        ? variables
        : [variables as string, undefined];

      if (method === "delete") return api.delete<TData>(path as string);
      if (method === "put")    return api.put<TData>(path as string, body);
      return api.post<TData>(path as string, body);
    },
    onSuccess: async (data, variables) => {
      if (successMessage !== false) {
        toast.success(successMessage ?? "Done");
      }
      await onSuccess?.(data, variables);
      for (const key of invalidates) {
        await queryClient.invalidateQueries({ queryKey: key });
      }
    },
    onError: (error, variables) => {
      toast.error(errorMessage ?? error.message ?? "Something went wrong");
      onError?.(error, variables);
    },
  });

  return mutation;
}
