import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import classification_report, roc_auc_score
import joblib
import json
from pathlib import Path

class MatchingModel:
    def __init__(self):
        self.model = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            random_state=42
        )
        self.education_levels = ['none', 'bachelor', 'master', 'phd']
        self.english_levels = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']

    def calculate_skills_match(self, cand_skills, vac_skills):
        """Подсчет процента совпадения навыков"""
        if isinstance(cand_skills, float) or isinstance(vac_skills, float):
            return 0

        cand_skills_set = set(str(cand_skills).split(', '))
        vac_skills_set = set(str(vac_skills).split(', '))

        if len(vac_skills_set) == 0:
            return 0

        return len(cand_skills_set & vac_skills_set) / len(vac_skills_set)

    def prepare_features(self, matches_df, candidates_df, vacancies_df):
        """Подготовка признаков без текстовых полей"""
        # Объединение таблиц
        merged = matches_df.merge(candidates_df, on='candidate_id')
        merged = merged.merge(vacancies_df, on='vacancy_id')

        features = pd.DataFrame()

        print(" Подсчет совпадения навыков...")
        features['skills_match'] = merged.apply(
            lambda row: self.calculate_skills_match(row['skills'], row['required_skills']), 
            axis=1
        )

        features['experience_years'] = merged['experience_years']
        features['min_experience'] = merged['min_experience']
        features['max_experience'] = merged['max_experience']
        features['exp_within_range'] = (
            (merged['experience_years'] >= merged['min_experience']) & 
            (merged['experience_years'] <= merged['max_experience'])
        ).astype(int)

        features['expected_salary'] = merged['expected_salary'] * 1000  
        features['min_salary'] = merged['min_salary']
        features['max_salary'] = merged['max_salary']
        features['salary_ratio'] = features['expected_salary'] / features['max_salary']

        features['spec_match'] = (merged['specialization_x'] == merged['specialization_y']).astype(int)

        features['education_cand'] = merged['education'].map(
            lambda x: self.education_levels.index(x) if x in self.education_levels else 0
        )
        features['education_req'] = merged['required_education'].map(
            lambda x: self.education_levels.index(x) if x in self.education_levels else 0
        )
        features['edu_match'] = (features['education_cand'] >= features['education_req']).astype(int)

        features['english_cand'] = merged['english_level'].map(
            lambda x: self.english_levels.index(x) if x in self.english_levels else 0
        )
        features['english_req'] = merged['english_required'].map(
            lambda x: self.english_levels.index(x) if x in self.english_levels else 0
        )
        features['eng_match'] = (features['english_cand'] >= features['english_req']).astype(int)

        features['has_portfolio'] = merged['has_portfolio']
        features['cand_skills_count'] = merged['skills'].str.count(',') + 1
        features['vac_skills_count'] = merged['required_skills'].str.count(',') + 1

        final_features = [
            'skills_match', 'experience_years', 'exp_within_range',
            'salary_ratio', 'spec_match', 'edu_match', 'eng_match',
            'has_portfolio', 'cand_skills_count', 'vac_skills_count'
        ]

        print(f" Подготовлено признаков: {len(final_features)}")
        print(f" Пример данных:\n{features[final_features].head()}")

        return features[final_features], merged['decision']

    def train(self, matches_path='data/matches.csv', 
              candidates_path='data/candidates.csv', 
              vacancies_path='data/vacancies.csv'):
        """Обучение модели"""
        print("📥 Загрузка данных...")
        matches_df = pd.read_csv(matches_path)
        candidates_df = pd.read_csv(candidates_path)
        vacancies_df = pd.read_csv(vacancies_path)

        print(" Подготовка признаков...")
        X, y = self.prepare_features(matches_df, candidates_df, vacancies_df)

        print(f"\n Размер данных: {X.shape}")
        print(f" Баланс классов:")
        print(y.value_counts())
        print(f"Процент приглашений: {y.mean()*100:.1f}%")

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        print("\n Обучение модели GradientBoostingClassifier...")
        self.model.fit(X_train, y_train)

        y_pred = self.model.predict(X_test)
        y_prob = self.model.predict_proba(X_test)[:, 1]

        print("\n" + "="*60)
        print(" Результаты на тестовой выборке:")
        print("="*60)
        print(f"ROC-AUC: {roc_auc_score(y_test, y_prob):.3f}")
        print(f"\nClassification Report:")
        print(classification_report(y_test, y_pred, 
                                    target_names=['Отказ ❌', 'Приглашение ✅'],
                                    zero_division=0))

        cv_scores = cross_val_score(self.model, X, y, cv=5, scoring='roc_auc')
        print(f" Cross-validation ROC-AUC: {cv_scores.mean():.3f} (+/- {cv_scores.std()*2:.3f})")

        feature_importance = pd.DataFrame({
            'feature': X.columns,
            'importance': self.model.feature_importances_
        }).sort_values('importance', ascending=False)

        print("\n Топ признаков:")
        print(feature_importance.to_string(index=False))

        Path('models').mkdir(exist_ok=True)
        joblib.dump(self.model, 'models/matching_model.pkl')

        metadata = {
            'features': X.columns.tolist(),
            'education_levels': self.education_levels,
            'english_levels': self.english_levels,
            'n_features': len(X.columns),
            'roc_auc': roc_auc_score(y_test, y_prob)
        }
        with open('models/model_metadata.json', 'w') as f:
            json.dump(metadata, f, indent=2)

        print("\n Модель сохранена в models/matching_model.pkl")
        print(" Метаданные сохранены в models/model_metadata.json")

        print("\n Примеры предсказаний:")
        for i in range(min(3, len(X_test))):
            prob = y_prob[i]
            actual = y_test.iloc[i]
            decision = "" if prob > 0.6 else ""
            print(f"\n  Кандидат {i+1}:")
            print(f"  Совпадение навыков: {X_test.iloc[i]['skills_match']:.2f}")
            print(f"  В диапазоне опыта: {'Да' if X_test.iloc[i]['exp_within_range'] else 'Нет'}")
            print(f"  Вероятность: {prob:.2f} {decision}")
            print(f"  Фактическое решение: {'' if actual else ''}")

        return self.model, X_test, y_test

if __name__ == '__main__':
    trainer = MatchingModel()
    model, X_test, y_test = trainer.train()
    print("\n Обучение успешно завершено!")
