// frontend/src/hooks/worker/useTicketComments.js
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchTicketComments, addTicketComment, updateTicketComment } from "@/lib/worker/api";

export function useTicketComments(ticketId) {
  const queryClient = useQueryClient();

  const commentsQuery = useQuery({
    queryKey: ["ticketComments", ticketId],
    queryFn: () => fetchTicketComments(ticketId),
    enabled: Boolean(ticketId),
    staleTime: 10000,
  });

  const addCommentMutation = useMutation({
    mutationFn: (text) => addTicketComment(ticketId, text),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ticketComments", ticketId] });
      queryClient.invalidateQueries({ queryKey: ["myDay"] });
    },
  });

  const updateCommentMutation = useMutation({
    mutationFn: ({ commentId, text }) => updateTicketComment(ticketId, commentId, text),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ticketComments", ticketId] });
    },
  });

  return {
    ...commentsQuery,
    comments: commentsQuery.data || [],
    addComment: addCommentMutation.mutateAsync,
    isAdding: addCommentMutation.isPending,
    updateComment: updateCommentMutation.mutateAsync,
    isUpdating: updateCommentMutation.isPending,
  };
}
