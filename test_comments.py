from services.drupal_comment_client import DrupalCommentClient

client = DrupalCommentClient()

comments = client.get_multiple_comments([
    16054094,
    16054099
])

for comment in comments:
    print(comment)
    print("------")