# Lab 3 Model Design

**Track selection:** Track A (churn prediction, required) + **Track B (offer generation with RAG)**

Full numbers: [evaluation report](lab3-evaluation-report.md) · Track B results: [examples and evaluation](lab3-evidence/track-b-examples.md)

## 1. Why gradient boosting

**Key facts:** 9,999 customers, 11 numeric features, 22% churners. The retention team needs to know why a customer is flagged. Final model: XGBoost, depth 3, AUC 0.784.

> XGBoost is the best option, because it works well at finding patterns in medium sized datasets and allows us to see which features are important in predicting customer churn. Logitstic regression isn't as good at picking up patterns and our dataset is too small to get good accuracy from a neural net.

## 2. What the features bought

| Model                         | AUC                                            |
| ----------------------------- | ---------------------------------------------- |
| Recency only                  | 0.722                                          |
| Full model (11 features)      | **0.784** (lift +0.062, 95% CI [0.042, 0.080]) |
| Full model + churn_risk_score | 0.773                                          |

**Key facts:** Recency and purchase frequency carry the most signal. Category diversity, channel mix, basket size and tenure carry the least.

> This lift is large because more customer features features increased the AUC (see CI). The recency and purchase frequency carry the most signal of churn risk. Category diversity, channel mix, basket size, and tenure were less useful because they contributed less to the predictions.

## 3. Why RAG instead of fine-tuning

**Key facts:** Offers must follow 4 policy documents that change over time. Every claim has to trace back to a policy. The starter prompt had 3 wrong facts written from memory.

> RAG allows us to tailor our output to the customer and personalize offers using customer information and company policies. Unlike fine-tuning, RAG can use updated policy documents without retraining the model. Our model has to trace back to a specific policy as well and using RAG lets us check what specific policies the model pulled from.

**Track B design choices**

| Choice        | What we used                                                | Why                                                                                                     |
| ------------- | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Embeddings    | Titan Text Embeddings v2                                    | Already verified in Pre-Lab 3; Cohere needs a separate subscription                                     |
| Vector store  | FAISS, in memory                                            | 44 chunks; free and fast                                                                                |
| Chunking      | One chunk per policy section, no overlap                    | Keeps each benefits table whole                                                                         |
| Retrieval     | 3 searches merged (tier benefits, offer rules, tier limits) | Scored best of the 5 strategies tested                                                                  |
| Generation    | Claude Haiku 4.5, temperature 0                             | Cheap, fast, and repeatable                                                                             |
| Re-ranking    | None                                                        | With 44 chunks, the right sections are already found; a second "verify" call removes unsupported claims |
| Tier mismatch | "As a Gold member, you currently receive..."                | The feature-store tier is an estimate, so benefits are stated conditionally                             |

## 4. With 10x the time or data

> If I had 10x more time, I would create a larger test set for the RAG system. We only used 4 test cases, and the Platinum context recall was 0.33. I would add more test cases based on the actual company policies to get more reliable results. I would know it worked if the system could find the correct policy information more consistently across different customer situations.
